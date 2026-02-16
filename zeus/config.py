"""Global configuration, constants, and compiled regexes."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


_USER_CONFIG_PATH = Path.home() / ".config" / "zeus" / "config.toml"


def _load_user_storage() -> dict[str, str]:
    if not _USER_CONFIG_PATH.is_file():
        return {}
    try:
        raw = tomllib.loads(_USER_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
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


_storage = _load_user_storage()

STATE_DIR = _resolve_dir(
    os.environ.get("ZEUS_STATE_DIR")
    or _storage.get("state_dir")
    or "/tmp"
)
MESSAGE_TMP_DIR = _resolve_dir(
    os.environ.get("ZEUS_MESSAGE_TMP_DIR")
    or _storage.get("message_tmp_dir")
    or "/tmp"
)

STATE_DIR.mkdir(parents=True, exist_ok=True)
MESSAGE_TMP_DIR.mkdir(parents=True, exist_ok=True)

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
