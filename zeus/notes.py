"""Persistent per-agent tasks storage."""

from __future__ import annotations

import json
import re

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


def load_agent_tasks() -> dict[str, str]:
    """Load tasks map keyed by stable agent key."""
    return load_agent_notes()


def save_agent_tasks(tasks: dict[str, str]) -> None:
    """Persist tasks map keyed by stable agent key."""
    save_agent_notes(tasks)


_TASK_HEADER_RE = re.compile(r"^\s*-\s*\[(?:\s*|[xX])\]\s*")
_DONE_TASK_HEADER_RE = re.compile(r"^\s*-\s*\[[xX]\]\s*")


def clear_done_note_tasks(note: str) -> tuple[str, int]:
    """Remove all done ``- [x]`` task blocks from note text.

    Returns ``(updated_note, removed_count)``.
    Done task blocks include the ``- [x]`` header line and all following lines
    up to the next task header.
    """
    lines = note.splitlines()
    if not lines:
        return "", 0

    out: list[str] = []
    removed = 0
    i = 0
    total = len(lines)

    while i < total:
        line = lines[i]
        if not _DONE_TASK_HEADER_RE.match(line):
            out.append(line)
            i += 1
            continue

        removed += 1
        i += 1
        while i < total and not _TASK_HEADER_RE.match(lines[i]):
            i += 1

    return "\n".join(out).rstrip(), removed


def clear_done_tasks(task_text: str) -> tuple[str, int]:
    """Remove all done task blocks from task text."""
    return clear_done_note_tasks(task_text)
