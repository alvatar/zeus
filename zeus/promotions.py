"""Persistent promotion state for sub-Hippeus relationships."""

from __future__ import annotations

import json

from .config import PROMOTED_SUB_HIPPEIS_FILE


def load_promoted_sub_hippeis() -> set[str]:
    """Load promoted sub-Hippeus ids."""
    try:
        raw = json.loads(PROMOTED_SUB_HIPPEIS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

    if not isinstance(raw, list):
        return set()

    out: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            continue
        clean = value.strip()
        if clean:
            out.add(clean)
    return out


def save_promoted_sub_hippeis(agent_ids: set[str]) -> None:
    """Persist promoted sub-Hippeus ids."""
    cleaned = sorted(
        {
            value.strip()
            for value in agent_ids
            if isinstance(value, str) and value.strip()
        }
    )
    PROMOTED_SUB_HIPPEIS_FILE.write_text(json.dumps(cleaned))
