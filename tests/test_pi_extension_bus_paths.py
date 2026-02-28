"""Static checks for pi extension bus paths used by worktree lifecycle tools."""

from pathlib import Path
import re


_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def test_worktree_tools_do_not_emit_to_legacy_agent_bus_path() -> None:
    text = _read("pi_extensions/zeus.ts")

    assert (
        'path.join(getStateDir(), "agent-bus", "inbox", "zeus", "new")'
        not in text
    )


def test_worktree_finalize_and_discard_emit_to_canonical_agent_bus_path() -> None:
    text = _read("pi_extensions/zeus.ts")

    canonical_line = 'const busDir = path.join(getBusDir(), "inbox", "zeus", "new");'
    assert text.count(canonical_line) >= 2

    assert re.search(
        r"if \(finalize\) \{.*?const busDir = path\.join\(getBusDir\(\), \"inbox\", \"zeus\", \"new\"\);",
        text,
        re.DOTALL,
    )
    assert re.search(
        r"async function doWorktreeDiscard\(.*?const busDir = path\.join\(getBusDir\(\), \"inbox\", \"zeus\", \"new\"\);",
        text,
        re.DOTALL,
    )
