"""Tests for blocked-agent priority rendering and retention."""

from __future__ import annotations

from rich.text import Text

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, State


class _RowKey:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[_RowKey] = []
        self.row_cells: dict[str, tuple[object, ...]] = {}

    def clear(self) -> None:
        self.rows = []
        self.row_cells = {}

    def add_row(self, *row: object, key: str) -> None:
        self.rows.append(_RowKey(key))
        self.row_cells[key] = tuple(row)


class _FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


def _agent(name: str, kitty_id: int, state: State, agent_id: str) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        state=state,
        agent_id=agent_id,
    )


def test_blocked_rows_render_numeric_priority_column(monkeypatch) -> None:
    app = ZeusApp()
    table = _FakeTable()
    status = _FakeStatus()

    blocker = _agent("blocker", 1, State.WORKING, "blocker-id")
    blocked = _agent("blocked", 2, State.IDLE, "blocked-id")
    app.agents = [blocker, blocked]
    app._agent_priorities = {"blocked": 2}
    app._agent_dependencies = {
        app._agent_dependency_key(blocked): app._agent_dependency_key(blocker),
    }

    def _query_one(selector: str, cls=None):  # noqa: ANN001
        if selector == "#agent-table":
            return table
        if selector == "#status-line":
            return status
        raise LookupError(selector)

    monkeypatch.setattr(app, "query_one", _query_one)
    monkeypatch.setattr(app, "_get_selected_row_key", lambda: None)
    monkeypatch.setattr(app, "_update_mini_map", lambda: None)
    monkeypatch.setattr(app, "_update_sparkline", lambda: None)

    app._render_agent_table_and_status()

    blocked_key = app._agent_key(blocked)
    p_idx = app._SPLIT_COLUMNS.index("P")
    pri_cell = table.row_cells[blocked_key][p_idx]

    assert isinstance(pri_cell, Text)
    assert pri_cell.plain == "2"
