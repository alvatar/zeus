"""Tests for priority-mode agent sorting order."""

from __future__ import annotations

import time

from zeus.dashboard.app import SortMode, ZeusApp
from zeus.models import AgentWindow, State, TmuxSession


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


def _agent(
    name: str,
    kitty_id: int,
    state: State,
    *,
    role: str = "",
    agent_id: str = "",
    parent_id: str = "",
) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        state=state,
        role=role,
        agent_id=agent_id,
        parent_id=parent_id,
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


def test_priority_sort_orders_priority_then_lexicographic(monkeypatch) -> None:
    app = ZeusApp()

    p1_z_working = _agent("p1-z-working", 1, State.WORKING)
    p1_a_idle_old = _agent("p1-a-idle-old", 2, State.IDLE)
    p1_m_idle_new = _agent("p1-m-idle-new", 3, State.IDLE)
    p2_b_working = _agent("p2-b-working", 4, State.WORKING)

    app.agents = [p1_z_working, p1_a_idle_old, p1_m_idle_new, p2_b_working]
    app._agent_priorities = {
        "p1-z-working": 1,
        "p1-a-idle-old": 1,
        "p1-m-idle-new": 1,
        "p2-b-working": 2,
    }

    now = time.time()
    app.state_changed_at = {
        app._agent_key(p1_z_working): now - 10,
        app._agent_key(p1_a_idle_old): now - 600,
        app._agent_key(p1_m_idle_new): now - 5,
        app._agent_key(p2_b_working): now - 300,
    }
    app.idle_since = {
        app._agent_key(p1_a_idle_old): now - 600,
        app._agent_key(p1_m_idle_new): now - 5,
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys == [
        app._agent_key(p1_a_idle_old),
        app._agent_key(p1_m_idle_new),
        app._agent_key(p1_z_working),
        app._agent_key(p2_b_working),
    ]


def test_priority_sort_ignores_idle_recency_within_same_priority(monkeypatch) -> None:
    app = ZeusApp()

    idle_z = _agent("idle-z", 10, State.IDLE)
    idle_a = _agent("idle-a", 11, State.IDLE)
    idle_m = _agent("idle-m", 12, State.IDLE)

    app.agents = [idle_z, idle_a, idle_m]
    app._agent_priorities = {
        "idle-z": 2,
        "idle-a": 2,
        "idle-m": 2,
    }

    now = time.time()
    app.state_changed_at = {
        app._agent_key(idle_z): now - 1,
        app._agent_key(idle_a): now - 100,
        app._agent_key(idle_m): now - 1000,
    }
    app.idle_since = {
        app._agent_key(idle_z): now - 1,
        app._agent_key(idle_a): now - 100,
        app._agent_key(idle_m): now - 1000,
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys == [
        app._agent_key(idle_a),
        app._agent_key(idle_m),
        app._agent_key(idle_z),
    ]


def test_priority_sort_pins_god_to_top(monkeypatch) -> None:
    app = ZeusApp()

    god = _agent("omega", 20, State.IDLE, role="god")
    high = _agent("alpha", 21, State.WORKING)

    app.agents = [high, god]
    app._agent_priorities = {
        "omega": 4,
        "alpha": 1,
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys[0] == app._agent_key(god)
    assert row_keys[1] == app._agent_key(high)


def test_alpha_sort_pins_god_to_top(monkeypatch) -> None:
    app = ZeusApp()
    app.sort_mode = SortMode.ALPHA

    god = _agent("zzz-god", 30, State.IDLE, role="god")
    alpha = _agent("aaa-worker", 31, State.WORKING)

    app.agents = [alpha, god]

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys[0] == app._agent_key(god)
    assert row_keys[1] == app._agent_key(alpha)


def test_branch_order_is_tmux_then_children_then_blocked(monkeypatch) -> None:
    app = ZeusApp()

    blocker = _agent("blocker", 40, State.WORKING, agent_id="blocker-id")
    blocker.tmux_sessions = [
        TmuxSession(
            name="viewer-a",
            command="pi",
            cwd="/tmp/project",
            attached=True,
        )
    ]
    child = _agent(
        "zzz-child",
        41,
        State.IDLE,
        agent_id="child-id",
        parent_id="blocker-id",
    )
    blocked = _agent(
        "aaa-blocked",
        42,
        State.IDLE,
        agent_id="blocked-id",
        parent_id="blocker-id",
    )

    app.agents = [blocker, blocked, child]
    app._agent_dependencies = {
        app._agent_dependency_key(blocked): app._agent_dependency_key(blocker),
    }

    row_keys = _render_row_keys(app, monkeypatch)

    assert row_keys == [
        app._agent_key(blocker),
        "tmux:viewer-a",
        app._agent_key(child),
        app._agent_key(blocked),
    ]
