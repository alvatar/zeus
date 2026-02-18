"""Runtime session path synchronization for Zeus-managed agents."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _session_map_dir() -> Path:
    raw = os.environ.get("ZEUS_SESSION_MAP_DIR", "/tmp/zeus-session-map")
    return Path(os.path.expanduser(raw))


def _session_map_file(agent_id: str) -> Path | None:
    clean = agent_id.strip()
    if not clean or not _AGENT_ID_RE.fullmatch(clean):
        return None
    return _session_map_dir() / f"{clean}.json"


def read_runtime_session_path(agent_id: str) -> str | None:
    """Read the latest session path published by the Zeus pi extension.

    Returns ``None`` when the runtime map is missing, malformed, or mismatched.
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

    session_path = payload.get("sessionPath")
    if not isinstance(session_path, str):
        return None

    expanded = os.path.expanduser(session_path.strip())
    if not expanded or not os.path.isabs(expanded):
        return None

    return expanded
