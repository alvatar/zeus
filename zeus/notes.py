"""Persistent per-agent notes storage."""

from __future__ import annotations

import json

from .config import AGENT_NOTES_FILE


def load_agent_notes() -> dict[str, str]:
    """Load notes map keyed by stable agent key."""
    try:
        raw = json.loads(AGENT_NOTES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def save_agent_notes(notes: dict[str, str]) -> None:
    """Persist notes map keyed by stable agent key."""
    filtered = {
        str(key): str(value)
        for key, value in notes.items()
        if isinstance(key, str) and isinstance(value, str) and value.strip()
    }
    AGENT_NOTES_FILE.write_text(json.dumps(filtered))
