"""Runtime session path synchronization for Zeus-managed agents."""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import time
from pathlib import Path


_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SESSION_MAP_MAX_AGE_DEFAULT_S = 24 * 60 * 60


def _session_map_dir() -> Path:
    default_dir = os.path.join(os.path.expanduser("~/.zeus"), "session-map")
    raw = os.environ.get("ZEUS_SESSION_MAP_DIR", default_dir)
    return Path(os.path.expanduser(raw))


def _session_map_file(agent_id: str) -> Path | None:
    clean = agent_id.strip()
    if not clean or not _AGENT_ID_RE.fullmatch(clean):
        return None
    return _session_map_dir() / f"{clean}.json"


def _session_map_max_age_s() -> float:
    raw = (os.environ.get("ZEUS_SESSION_MAP_MAX_AGE_S") or "").strip()
    if not raw:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    try:
        parsed = float(raw)
    except ValueError:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    if parsed <= 0:
        return float(_SESSION_MAP_MAX_AGE_DEFAULT_S)
    return parsed


def _parse_updated_at_timestamp(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return None

    return dt.timestamp()


def read_runtime_session_path(agent_id: str) -> str | None:
    """Read the latest session path published by the Zeus pi extension.

    Returns ``None`` when the runtime map is missing, malformed, mismatched,
    stale, or points at a missing session file.
    """
    map_file = _session_map_file(agent_id)
    if map_file is None:
        return None

    try:
        payload = json.loads(map_file.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    expected_agent_id = agent_id.strip()
    payload_agent_id = payload.get("agentId")
    if isinstance(payload_agent_id, str):
        if payload_agent_id.strip() and payload_agent_id.strip() != expected_agent_id:
            return None

    updated_at_ts = _parse_updated_at_timestamp(payload.get("updatedAt"))
    if updated_at_ts is None:
        return None

    now_ts = time.time()
    if now_ts - updated_at_ts > _session_map_max_age_s():
        return None

    session_path = payload.get("sessionPath")
    if not isinstance(session_path, str):
        return None

    expanded = os.path.expanduser(session_path.strip())
    if not expanded or not os.path.isabs(expanded):
        return None
    if not os.path.isfile(expanded):
        return None

    return expanded
