"""Persistent interact-input history storage."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .config import INPUT_HISTORY_DIR, INPUT_HISTORY_MAX


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug[:40] or "history"


def history_path_for_key(target_key: str) -> Path:
    """Return deterministic on-disk history path for a target key."""
    digest = hashlib.sha1(target_key.encode("utf-8")).hexdigest()[:16]
    slug = _slugify(target_key)
    return INPUT_HISTORY_DIR / f"{slug}-{digest}.json"


def load_history(target_key: str) -> list[str]:
    """Load history entries for a target key."""
    if not target_key.strip():
        return []
    path = history_path_for_key(target_key)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    entries: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            entries.append(item)
    return entries[-INPUT_HISTORY_MAX:]


def save_history(target_key: str, entries: list[str]) -> None:
    """Persist history entries for a target key."""
    if not target_key.strip():
        return
    filtered = [entry for entry in entries if entry.strip()]
    path = history_path_for_key(target_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(filtered[-INPUT_HISTORY_MAX:]))


def append_history(target_key: str, entry: str) -> list[str]:
    """Append one entry to a target history and persist it."""
    message = entry.strip()
    if not target_key.strip() or not message:
        return []
    entries = load_history(target_key)
    if not entries or entries[-1] != message:
        entries.append(message)
    save_history(target_key, entries)
    return load_history(target_key)


def prune_histories(live_target_keys: set[str]) -> None:
    """Delete history files for targets not present in the provided live set."""
    INPUT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    keep: set[str] = {
        history_path_for_key(key).name
        for key in live_target_keys
        if key.strip()
    }
    for path in INPUT_HISTORY_DIR.glob("*.json"):
        if path.name not in keep:
            try:
                path.unlink()
            except OSError:
                pass
