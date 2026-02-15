"""Persistent per-agent dependency mapping.

Mapping shape: {blocked_agent_id: blocker_agent_id}
"""

from __future__ import annotations

import json

from .config import AGENT_DEPENDENCIES_FILE


def load_agent_dependencies() -> dict[str, str]:
    """Load dependency map keyed by stable agent id."""
    try:
        raw = json.loads(AGENT_DEPENDENCIES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, str] = {}
    for blocked_id, blocker_id in raw.items():
        if not isinstance(blocked_id, str) or not isinstance(blocker_id, str):
            continue
        b = blocked_id.strip()
        r = blocker_id.strip()
        if not b or not r or b == r:
            continue
        out[b] = r
    return out


def save_agent_dependencies(deps: dict[str, str]) -> None:
    """Persist dependency map keyed by stable agent id."""
    filtered = {
        str(blocked_id): str(blocker_id)
        for blocked_id, blocker_id in deps.items()
        if isinstance(blocked_id, str)
        and isinstance(blocker_id, str)
        and blocked_id.strip()
        and blocker_id.strip()
        and blocked_id != blocker_id
    }
    AGENT_DEPENDENCIES_FILE.write_text(json.dumps(filtered))
