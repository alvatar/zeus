"""Tests for mini-map row pairing layout."""

from __future__ import annotations

from types import SimpleNamespace

from zeus.dashboard.app import SortMode, ZeusApp
from zeus.models import AgentWindow


class _DummyMini:
    def __init__(self, width: int) -> None:
        self.classes: set[str] = set()
        self.size = SimpleNamespace(width=width)
        self.text: str = ""

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)

    def update(self, text: str) -> None:
        self.text = text


def _agent(name: str, kitty_id: int) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def test_minimap_wraps_as_paired_marker_and_label_rows(monkeypatch) -> None:
    app = ZeusApp()
    app.sort_mode = SortMode.ALPHA
    app._show_minimap = True
    app.agents = [
        _agent("alpha", 1),
        _agent("beta", 2),
        _agent("gamma", 3),
        _agent("delta", 4),
    ]

    mini = _DummyMini(width=20)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: mini)

    app._update_mini_map()

    lines = mini.text.splitlines()
    assert len(lines) == 4

    assert "▄" in lines[0]
    assert "alpha" in lines[1]
    assert "beta" in lines[1]
    assert "delta" not in lines[1]
    assert "gamma" not in lines[1]

    assert "▄" in lines[2]
    assert "delta" in lines[3]
    assert "gamma" in lines[3]
    assert "alpha" not in lines[3]
    assert "beta" not in lines[3]


def test_minimap_keeps_single_pair_when_width_is_sufficient(monkeypatch) -> None:
    app = ZeusApp()
    app.sort_mode = SortMode.ALPHA
    app._show_minimap = True
    app.agents = [
        _agent("alpha", 1),
        _agent("beta", 2),
        _agent("gamma", 3),
    ]

    mini = _DummyMini(width=120)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: mini)

    app._update_mini_map()

    lines = mini.text.splitlines()
    assert len(lines) == 2
    assert "▄" in lines[0]
    assert "alpha" in lines[1]
    assert "beta" in lines[1]
    assert "gamma" in lines[1]
