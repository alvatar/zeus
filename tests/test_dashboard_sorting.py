"""Tests for priority-mode agent sorting order."""

from __future__ import annotations

import time

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, State


class _RowKey:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[_RowKey] = []

    def clear(self) -> None:
        self.rows = []

    def add_row(self, *row: object, key: str) -> None:  # noqa: ARG002
        self.rows.append(_RowKey(key))


class _FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


def _agent(name: str, kitty_id: int, state: State) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        state=state,
    )


def _render_row_keys(app: ZeusApp, monkeypatch) -> list[str]:
    table = _FakeTable()
    status = _FakeStatus()

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
    return [row.value for row in table.rows]


def test_priority_sort_orders_priority_then_state_then_idle_time(monkeypatch) -> None:
    app = ZeusApp()

    p1_idle_old = _agent("p1-idle-old", 1, State.IDLE)
    p1_working = _agent("p1-working", 2, State.WORKING)
    p1_idle_new = _agent("p1-idle-new", 3, State.IDLE)
    p2_working = _agent("p2-working", 4, State.WORKING)

    app.agents = [p1_idle_old, p1_working, p1_idle_new, p2_working]
    app._agent_priorities = {
        "p1-idle-old": 1,
        "p1-working": 1,
        "p1-idle-new": 1,
        "p2-working": 2,
    }

    now = time.time()
    app.state_changed_at = {
        app._agent_key(p1_idle_old): now - 300,
        app._agent_key(p1_working): now - 100,
        app._agent_key(p1_idle_new): now - 20,
        app._agent_key(p2_working): now - 200,
    }
    app.idle_since = {
        app._agent_key(p1_idle_old): now - 300,
        app._agent_key(p1_idle_new): now - 20,
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys == [
        app._agent_key(p1_working),
        app._agent_key(p1_idle_new),
        app._agent_key(p1_idle_old),
        app._agent_key(p2_working),
    ]


def test_priority_sort_places_longer_idle_lower_within_same_bucket(monkeypatch) -> None:
    app = ZeusApp()

    idle_a = _agent("idle-a", 10, State.IDLE)
    idle_b = _agent("idle-b", 11, State.IDLE)
    idle_c = _agent("idle-c", 12, State.IDLE)

    app.agents = [idle_a, idle_b, idle_c]
    app._agent_priorities = {
        "idle-a": 2,
        "idle-b": 2,
        "idle-c": 2,
    }

    now = time.time()
    app.state_changed_at = {
        app._agent_key(idle_a): now - 5,
        app._agent_key(idle_b): now - 60,
        app._agent_key(idle_c): now - 600,
    }
    app.idle_since = {
        app._agent_key(idle_a): now - 5,
        app._agent_key(idle_b): now - 60,
        app._agent_key(idle_c): now - 600,
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys == [
        app._agent_key(idle_a),
        app._agent_key(idle_b),
        app._agent_key(idle_c),
    ]
