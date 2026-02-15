"""OpenAI usage cache reader and background refresh helpers."""

from __future__ import annotations

import json
import os
from glob import glob
from pathlib import Path
import subprocess
import sys
import time

from .config import OPENAI_USAGE_CACHE
from .models import OpenAIUsageData


def _openai_log(msg: str) -> None:
    try:
        ts: str = time.strftime("%Y-%m-%d %H:%M:%S")
        with open("/tmp/zeus-openai.log", "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def _load_openai_access_token() -> str:
    auth_path: Path = Path.home() / ".pi" / "agent" / "auth.json"
    try:
        data: dict = json.loads(auth_path.read_text())
        token_info: dict = data.get("openai-codex", {})
        token: str = token_info.get("access", "")
        expires: int = token_info.get("expires", 0)
        if token:
            _openai_log(
                f"loaded openai-codex oauth access token from {auth_path} "
                f"(expires_ms={expires})"
            )
        if token and (not expires or expires > int(time.time() * 1000)):
            return token
        if token:
            _openai_log("oauth access token appears expired, trying anyway")
            return token
        _openai_log("no openai-codex access token present in auth.json")
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
        _openai_log(f"failed to read {auth_path}: {e}")
    return ""


def _spawn_openai_fetch() -> None:
    """Spawn a helper process to fetch OpenAI usage."""
    try:
        zeus_path: str = str(Path(sys.argv[0]).expanduser().resolve())
        with open("/tmp/zeus-openai-fetch.err", "a") as err:
            subprocess.Popen(
                [sys.executable, zeus_path, "fetch-openai-usage"],
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
            )
    except (FileNotFoundError, OSError, ValueError) as e:
        _openai_log(f"failed to spawn openai fetch helper: {e}")


def fetch_openai_usage() -> None:
    """Fetch OpenAI usage via WHAM endpoint, falling back to API headers."""
    api_key: str | None = os.environ.get("OPENAI_API_KEY")
    if api_key:
        _openai_log("auth source: OPENAI_API_KEY env")

    if not api_key:
        try:
            for socket in glob("/tmp/kitty-*"):
                raw: str = subprocess.run(
                    ["kitty", "@", "--to", f"unix:{socket}", "ls"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                ).stdout
                data: list[dict] = json.loads(raw) if raw else []
                for os_win in data:
                    for tab in os_win.get("tabs", []):
                        for win in tab.get("windows", []):
                            key = win.get("env", {}).get("OPENAI_API_KEY")
                            if key:
                                api_key = key
                                _openai_log(
                                    f"auth source: kitty window env "
                                    f"(socket={socket})"
                                )
                                break
                        if api_key:
                            break
                    if api_key:
                        break
                if api_key:
                    break
        except (
            subprocess.TimeoutExpired,
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ) as e:
            _openai_log(f"failed to scan kitty env for OPENAI_API_KEY: {e}")

    if not api_key:
        api_key = _load_openai_access_token()
        if api_key:
            _openai_log(
                "auth source: pi oauth token "
                "(~/.pi/agent/auth.json openai-codex.access)"
            )

    if not api_key:
        _openai_log("no auth found (OPENAI_API_KEY or pi oauth)")
        return

    # 1) Try ChatGPT backend WHAM usage endpoint
    try:
        import urllib.error
        import urllib.request

        token: str = api_key
        base_urls: list[str] = [
            "https://chatgpt.com/backend-api",
            "https://chat.openai.com/backend-api",
        ]
        for base in base_urls:
            url: str = f"{base}/wham/usage"
            _openai_log(f"requesting {url}")
            req = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "zeus",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    body: str = response.read().decode(errors="replace")
                    data_resp: dict = json.loads(body)

                    rl: dict = data_resp.get("rate_limit") or {}
                    primary: dict = rl.get("primary_window") or {}
                    secondary: dict = rl.get("secondary_window") or {}

                    def _pct(win: dict) -> float:
                        try:
                            return float(win.get("used_percent", 0.0))
                        except (TypeError, ValueError):
                            return 0.0

                    def _reset_at(win: dict) -> str:
                        ra = win.get("reset_at")
                        if ra is None:
                            return ""
                        try:
                            secs_val: int = int(ra)
                            from datetime import datetime, timezone

                            return datetime.fromtimestamp(
                                secs_val,
                                tz=timezone.utc,
                            ).isoformat()
                        except (TypeError, ValueError, OSError):
                            return str(ra)

                    cache_data: dict = {
                        "requests_limit": int(primary.get("limit", 0) or 0),
                        "requests_remaining": int(primary.get("remaining", 0) or 0),
                        "tokens_limit": int(secondary.get("limit", 0) or 0),
                        "tokens_remaining": int(secondary.get("remaining", 0) or 0),
                        "requests_pct": _pct(primary),
                        "tokens_pct": _pct(secondary),
                        "requests_resets_at": _reset_at(primary),
                        "tokens_resets_at": _reset_at(secondary),
                        "timestamp": time.time(),
                        "source": url,
                    }
                    OPENAI_USAGE_CACHE.write_text(json.dumps(cache_data))
                    _openai_log(f"cached wham usage to {OPENAI_USAGE_CACHE}")
                    return
            except urllib.error.HTTPError as e:
                err_body: str = e.read(500).decode(errors="replace")
                _openai_log(f"HTTPError {e.code} from {url}: {err_body}")
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as e:
                _openai_log(f"fetch failed for {url}: {type(e).__name__}: {e}")

    except (ImportError, OSError) as e:
        _openai_log(f"wham usage attempt failed: {type(e).__name__}: {e}")

    # 2) Fallback: API platform rate-limit headers
    try:
        import urllib.error
        import urllib.request

        url = "https://api.openai.com/v1/chat/completions"
        payload: dict = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        _openai_log(f"fallback requesting {url} to read rate limit headers")
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            headers = response.headers
            cache_data = {
                "requests_limit": int(headers.get("x-ratelimit-limit-requests", 0) or 0),
                "requests_remaining": int(headers.get("x-ratelimit-remaining-requests", 0) or 0),
                "tokens_limit": int(headers.get("x-ratelimit-limit-tokens", 0) or 0),
                "tokens_remaining": int(headers.get("x-ratelimit-remaining-tokens", 0) or 0),
                "requests_resets_at": headers.get("x-ratelimit-reset-requests", ""),
                "tokens_resets_at": headers.get("x-ratelimit-reset-tokens", ""),
                "timestamp": time.time(),
                "source": url,
            }
            OPENAI_USAGE_CACHE.write_text(json.dumps(cache_data))
            _openai_log(f"cached api rate limits to {OPENAI_USAGE_CACHE}")
    except ImportError as e:
        _openai_log(f"fallback fetch failed: {type(e).__name__}: {e}")
    except urllib.error.HTTPError as e:
        body_err: str = e.read(500).decode(errors="replace")
        _openai_log(f"fallback HTTPError {e.code}: {body_err}")
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as e:
        _openai_log(f"fallback fetch failed: {type(e).__name__}: {e}")


_last_openai_fetch_attempt: float = 0.0


def read_openai_usage() -> OpenAIUsageData:
    """Read cached OpenAI usage. Cache is populated by background fetch."""
    global _last_openai_fetch_attempt

    def _maybe_fetch(reason: str, min_interval_s: float = 5.0) -> None:
        global _last_openai_fetch_attempt
        now: float = time.time()
        if now - _last_openai_fetch_attempt >= min_interval_s:
            _openai_log(f"triggering background fetch ({reason})")
            _last_openai_fetch_attempt = now
            _spawn_openai_fetch()

    try:
        data = json.loads(OPENAI_USAGE_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        _openai_log(f"openai cache read failed: {type(e).__name__}: {e}")
        _maybe_fetch("cache-missing")
        return OpenAIUsageData()

    age: float = time.time() - data.get("timestamp", 0)
    if age > 10:
        _maybe_fetch(f"cache-stale age={age:.1f}s")

    req_limit: int = int(data.get("requests_limit", 0) or 0)
    req_remaining: int = int(data.get("requests_remaining", 0) or 0)
    tok_limit: int = int(data.get("tokens_limit", 0) or 0)
    tok_remaining: int = int(data.get("tokens_remaining", 0) or 0)

    req_pct: float
    if "requests_pct" in data:
        req_pct = float(data.get("requests_pct") or 0.0)
    else:
        req_pct = (
            ((req_limit - req_remaining) / req_limit * 100)
            if req_limit > 0
            else 0.0
        )

    tok_pct: float
    if "tokens_pct" in data:
        tok_pct = float(data.get("tokens_pct") or 0.0)
    else:
        tok_pct = (
            ((tok_limit - tok_remaining) / tok_limit * 100)
            if tok_limit > 0
            else 0.0
        )

    available: bool = req_limit > 0 or tok_limit > 0 or req_pct > 0 or tok_pct > 0
    if not available:
        _maybe_fetch("cache-present-but-empty")

    return OpenAIUsageData(
        requests_pct=req_pct,
        tokens_pct=tok_pct,
        requests_limit=req_limit,
        requests_remaining=req_remaining,
        tokens_limit=tok_limit,
        tokens_remaining=tok_remaining,
        requests_resets_at=data.get("requests_resets_at", ""),
        tokens_resets_at=data.get("tokens_resets_at", ""),
        available=available,
    )
