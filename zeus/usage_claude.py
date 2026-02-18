"""Claude usage cache reader and refresh helpers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .config import STATE_DIR, USAGE_CACHE
from .models import UsageData


_CLAUDE_CREDENTIALS_FILE: Path = (
    Path.home() / ".claude" / ".credentials.json"
)
_CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_CLAUDE_CACHE_MAX_AGE_S = 60.0
_CLAUDE_LOG_FILE = STATE_DIR / "zeus-claude.log"
_CLAUDE_FETCH_ERR_FILE = STATE_DIR / "zeus-claude-fetch.err"

_last_claude_fetch_attempt: float = 0.0


def _claude_log(msg: str) -> None:
    try:
        ts: str = time.strftime("%Y-%m-%d %H:%M:%S")
        with _CLAUDE_LOG_FILE.open("a") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def _load_claude_oauth_info() -> tuple[str, bool]:
    """Return (access_token, is_expired)."""
    try:
        data: dict = json.loads(_CLAUDE_CREDENTIALS_FILE.read_text())
        oauth: dict = data.get("claudeAiOauth", {})
        token: str = oauth.get("accessToken") or ""
        expires_at: int = int(oauth.get("expiresAt") or 0)
        expired: bool = expires_at > 0 and int(time.time() * 1000) > expires_at
        return token, expired
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return "", False


def _refresh_claude_oauth_token() -> bool:
    """Trigger Claude CLI once to refresh OAuth token in credentials file."""
    try:
        proc = subprocess.run(
            ["claude", "-p", "hi", "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=20,
            start_new_session=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        _claude_log(f"token refresh command failed: {type(e).__name__}: {e}")
        return False

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        _claude_log(
            "token refresh command exited non-zero "
            f"(code={proc.returncode}, tail={stderr_tail[0]!r})"
        )
        return False

    _claude_log("token refresh command completed")
    return True


def _fetch_claude_usage_once(access_token: str) -> tuple[int, str]:
    """Return (HTTP status, response body) from Anthropic OAuth usage API."""
    try:
        req = urllib.request.Request(
            _CLAUDE_USAGE_URL,
            method="GET",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            body = resp.read().decode(errors="replace")
            return status, body
    except urllib.error.HTTPError as e:
        body = e.read(500).decode(errors="replace")
        return int(e.code), body
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
    ) as e:
        _claude_log(f"usage fetch failed: {type(e).__name__}: {e}")
        return 0, ""


def fetch_claude_usage() -> None:
    """Fetch Claude usage cache directly, refreshing OAuth token if needed."""
    token, expired = _load_claude_oauth_info()

    if not token or expired:
        _claude_log(
            "oauth token missing/expired; triggering claude cli refresh"
        )
        if not _refresh_claude_oauth_token():
            return
        token, _expired = _load_claude_oauth_info()
        if not token:
            _claude_log("token still missing after refresh")
            return

    status, body = _fetch_claude_usage_once(token)

    if status in (401, 403):
        _claude_log(f"usage API rejected token ({status}); refreshing once")
        if not _refresh_claude_oauth_token():
            return
        token, _ = _load_claude_oauth_info()
        if not token:
            _claude_log("token missing after auth retry")
            return
        status, body = _fetch_claude_usage_once(token)

    if status != 200 or not body:
        _claude_log(f"usage API request failed (status={status})")
        return

    try:
        parsed: dict = json.loads(body)
    except (json.JSONDecodeError, TypeError, ValueError):
        _claude_log("usage API returned non-JSON body")
        return

    if not parsed.get("five_hour"):
        _claude_log("usage API payload missing five_hour")
        return

    try:
        USAGE_CACHE.write_text(body)
        _claude_log(f"cached Claude usage to {USAGE_CACHE}")
    except OSError as e:
        _claude_log(f"failed writing Claude cache: {e}")


def _spawn_claude_fetch() -> None:
    """Spawn a helper process to refresh Claude OAuth/usage cache."""
    try:
        zeus_path: str = str(Path(sys.argv[0]).expanduser().resolve())
        with _CLAUDE_FETCH_ERR_FILE.open("a") as err:
            subprocess.Popen(
                [sys.executable, zeus_path, "fetch-claude-usage"],
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
            )
    except (FileNotFoundError, OSError, ValueError) as e:
        _claude_log(f"failed to spawn claude fetch helper: {e}")


def read_usage() -> UsageData:
    global _last_claude_fetch_attempt

    def _maybe_fetch(reason: str, min_interval_s: float = 60.0) -> None:
        global _last_claude_fetch_attempt
        now: float = time.time()
        if now - _last_claude_fetch_attempt >= min_interval_s:
            _claude_log(f"triggering background fetch ({reason})")
            _last_claude_fetch_attempt = now
            _spawn_claude_fetch()

    try:
        data: dict = json.loads(USAGE_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        _claude_log(f"claude cache read failed: {type(e).__name__}: {e}")
        _maybe_fetch("cache-missing")
        return UsageData()

    try:
        age: float = time.time() - USAGE_CACHE.stat().st_mtime
        if age > _CLAUDE_CACHE_MAX_AGE_S:
            _maybe_fetch(f"cache-stale age={age:.1f}s")
    except OSError:
        pass

    usage = UsageData(
        session_pct=data.get("five_hour", {}).get("utilization") or 0,
        week_pct=data.get("seven_day", {}).get("utilization") or 0,
        extra_pct=data.get("extra_usage", {}).get("utilization") or 0,
        extra_used=data.get("extra_usage", {}).get("used_credits") or 0,
        extra_limit=data.get("extra_usage", {}).get("monthly_limit") or 0,
        session_resets_at=data.get("five_hour", {}).get("resets_at") or "",
        week_resets_at=data.get("seven_day", {}).get("resets_at") or "",
        available=True,
    )

    if "five_hour" not in data:
        _maybe_fetch("cache-present-but-missing-five-hour")

    return usage
