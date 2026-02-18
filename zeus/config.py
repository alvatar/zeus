"""Global configuration, constants, and compiled regexes."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


ZEUS_HOME = Path(os.environ.get("ZEUS_HOME") or "~/.zeus").expanduser()

_USER_CONFIG_PATHS: tuple[Path, ...] = (
    ZEUS_HOME / "config.toml",
    Path.home() / ".config" / "zeus" / "config.toml",  # legacy fallback
)


def _load_user_storage() -> dict[str, str]:
    raw: dict[str, object] | None = None
    for config_path in _USER_CONFIG_PATHS:
        if not config_path.is_file():
            continue
        try:
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if isinstance(parsed, dict):
            raw = parsed
            break

    if raw is None:
        return {}

    storage = raw.get("storage")
    if not isinstance(storage, dict):
        return {}

    out: dict[str, str] = {}
    state_dir = storage.get("state_dir")
    if isinstance(state_dir, str) and state_dir.strip():
        out["state_dir"] = state_dir.strip()

    message_tmp_dir = storage.get("message_tmp_dir")
    if isinstance(message_tmp_dir, str) and message_tmp_dir.strip():
        out["message_tmp_dir"] = message_tmp_dir.strip()

    return out


def _resolve_dir(raw: str) -> Path:
    return Path(os.path.expanduser(raw)).expanduser()


def _ensure_writable_dir(path: Path, fallback: Path) -> Path:
    """Ensure directory exists, falling back when creation is denied."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


_storage = _load_user_storage()
_fallback_zeus_home = _resolve_dir("/tmp/zeus")
ZEUS_HOME = _ensure_writable_dir(ZEUS_HOME, _fallback_zeus_home)

STATE_DIR = _ensure_writable_dir(
    _resolve_dir(
        os.environ.get("ZEUS_STATE_DIR")
        or _storage.get("state_dir")
        or str(ZEUS_HOME)
    ),
    ZEUS_HOME,
)
MESSAGE_TMP_DIR = _ensure_writable_dir(
    _resolve_dir(
        os.environ.get("ZEUS_MESSAGE_TMP_DIR")
        or _storage.get("message_tmp_dir")
        or str(ZEUS_HOME / "messages")
    ),
    ZEUS_HOME / "messages",
)

NAMES_FILE = STATE_DIR / "zeus-names.json"
AGENT_IDS_FILE = STATE_DIR / "zeus-agent-ids.json"
INPUT_HISTORY_DIR = STATE_DIR / "zeus-input-history"
PRIORITIES_FILE = STATE_DIR / "zeus-priorities.json"
PANEL_VISIBILITY_FILE = STATE_DIR / "zeus-panel-visibility.json"
AGENT_NOTES_FILE = STATE_DIR / "zeus-agent-notes.json"
AGENT_DEPENDENCIES_FILE = STATE_DIR / "zeus-agent-dependencies.json"
USAGE_CACHE = STATE_DIR / "claude-usage-cache.json"
OPENAI_USAGE_CACHE = STATE_DIR / "openai-usage-cache.json"
MESSAGE_QUEUE_DIR = STATE_DIR / "zeus-message-queue"
MESSAGE_RECEIPTS_FILE = STATE_DIR / "zeus-message-receipts.json"

INPUT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
MESSAGE_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

# Pi spinner frames (from pi-tui Loader component)
SPINNER_RE = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]\s+\S")

# Footer parsing (from usage-bars.ts extension output)
MODEL_RE = re.compile(r"^(\S+)\s*(?:\((\w+)\))?")
CTX_RE = re.compile(r"Ctx\([^)]*\):[█░]+\((\d+\.?\d*)%\)")
TOKENS_RE = re.compile(r"↑([\d.]+[kM]?)\s+↓([\d.]+[kM]?)")

# Pi session storage
AGENT_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"
