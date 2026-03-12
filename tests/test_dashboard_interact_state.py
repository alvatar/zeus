"""Tests for dashboard-owned selection and interact draft state."""

from __future__ import annotations

from types import SimpleNamespace

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, State


class _RowKey:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[_RowKey] = []
        self.cursor_row: int | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def clear(self) -> None:
        self.rows = []

    def add_row(self, *row: object, key: str) -> None:  # noqa: ARG002
        self.rows.append(_RowKey(key))

    def move_cursor(self, row: int) -> None:
        self.cursor_row = row


class _FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


class _DummyInteractInput:
    def __init__(self, text: str = "") -> None:
        self.id = "interact-input"
        self.text = text
        self.styles = SimpleNamespace(height=3)
        self.size = SimpleNamespace(width=80)

    def clear(self) -> None:
        self.text = ""


def _agent(name: str, kitty_id: int) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        state=State.IDLE,
        agent_id=f"agent-{kitty_id}",
    )


def test_render_agent_table_restores_app_owned_selected_row(monkeypatch) -> None:
    app = ZeusApp()
    a1 = _agent("alpha", 1)
    a2 = _agent("beta", 2)
    app.agents = [a1, a2]
    app._selected_row_key = app._agent_key(a2)

    table = _FakeTable()
    status = _FakeStatus()

    def _query_one(selector: str, cls=None):  # noqa: ANN001, ARG001
        if selector == "#agent-table":
            return table
        if selector == "#status-line":
            return status
        raise LookupError(selector)

    monkeypatch.setattr(app, "query_one", _query_one)
    monkeypatch.setattr(app, "_update_mini_map", lambda: None)
    monkeypatch.setattr(app, "_update_sparkline", lambda: None)

    assert app._render_agent_table_and_status() is True
    assert app._selected_row_key == app._agent_key(a2)
    assert table.cursor_row == 1


def test_refresh_interact_panel_does_not_touch_widget_for_same_target(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1)
    agent_key = app._agent_key(agent)

    app.agents = [agent]
    app._selected_row_key = agent_key
    app._interact_agent_key = agent_key
    app._interact_input_target_key = f"agent:{agent_key}"

    refreshed: list[bool] = []

    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: (_ for _ in ()).throw(AssertionError(selector)))
    monkeypatch.setattr(app, "_set_interact_target_name", lambda _name: None)
    monkeypatch.setattr(app, "_set_interact_editable", lambda _editable: None)
    monkeypatch.setattr(app, "_update_interact_stream", lambda: refreshed.append(True))

    app._refresh_interact_panel()

    assert refreshed == [True]
    assert app._interact_agent_key == agent_key


def test_on_text_area_changed_updates_app_owned_interact_draft(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("alpha", 1)
    agent_key = app._agent_key(agent)
    input_widget = _DummyInteractInput("hello world")

    app._interact_agent_key = agent_key

    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: input_widget)

    app.on_text_area_changed(SimpleNamespace(text_area=input_widget))

    assert app._interact_drafts == {f"agent:{agent_key}": "hello world"}
    assert input_widget.styles.height >= 3


def test_row_highlight_updates_app_owned_selected_row(monkeypatch) -> None:
    app = ZeusApp()
    timer = SimpleNamespace(stop=lambda: None)

    monkeypatch.setattr(app, "set_timer", lambda _delay, _fn: timer)

    event = SimpleNamespace(row_key=SimpleNamespace(value="row-2"))
    app.on_data_table_row_highlighted(event)

    assert app._selected_row_key == "row-2"
    assert app._highlight_timer is timer
