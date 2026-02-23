"""Load message presets from ~/.zeus/message-presets.toml."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from .config import ZEUS_HOME

PRESETS_FILE = ZEUS_HOME / "message-presets.toml"

_QUICK_SLOTS = ("1", "2", "3", "4")

_DEFAULT_QUICK: list[tuple[str, str]] = [
    ("Research", "Research preset not configured."),
    ("Plan", "Plan preset not configured."),
    ("Freeze", "Freeze preset not configured."),
    ("Build", "Build preset not configured."),
]

_DEFAULT_PREMADE: list[tuple[str, str]] = [
    ("Self-review", "Review your output against your own claims again"),
]


def _load_toml() -> dict[str, object] | None:
    if not PRESETS_FILE.is_file():
        return None
    try:
        return tomllib.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(
            f"[zeus] warning: failed to parse {PRESETS_FILE}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None


def load_quick_presets() -> list[tuple[str, str]]:
    """Load quick.1–quick.4 presets. Returns exactly 4 entries."""
    data = _load_toml()
    if data is None:
        return list(_DEFAULT_QUICK)

    quick = data.get("quick")
    if not isinstance(quick, dict):
        return list(_DEFAULT_QUICK)

    result: list[tuple[str, str]] = []
    for slot in _QUICK_SLOTS:
        entry = quick.get(slot)
        if not isinstance(entry, dict):
            result.append(_DEFAULT_QUICK[len(result)])
            continue
        name = str(entry.get("name", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not name:
            result.append(_DEFAULT_QUICK[len(result)])
            continue
        result.append((name, text))

    return result


def load_premade_templates() -> list[tuple[str, str]]:
    """Load [[premade]] templates. Returns at least the default entry."""
    data = _load_toml()
    if data is None:
        return list(_DEFAULT_PREMADE)

    raw = data.get("premade")
    if not isinstance(raw, list):
        return list(_DEFAULT_PREMADE)

    result: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        text = str(entry.get("text", "")).strip()
        if not name:
            continue
        result.append((name, text))

    return result if result else list(_DEFAULT_PREMADE)
