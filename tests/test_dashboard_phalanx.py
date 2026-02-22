"""Tests for Polemarch/Hoplite phalanx rendering and classification."""

from __future__ import annotations

from rich.text import Text

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, TmuxSession


def _agent(agent_id: str = "agent-1", role: str = "") -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="polemarch",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
        agent_id=agent_id,
        role=role,
    )


def _tmux(
    *,
    name: str = "sess",
    role: str = "",
    owner_id: str = "",
    phalanx_id: str = "",
    attached: bool = True,
) -> TmuxSession:
    return TmuxSession(
        name=name,
        command="pi",
        cwd="/tmp/project",
        role=role,
        owner_id=owner_id,
        phalanx_id=phalanx_id,
        attached=attached,
    )


class _FakeRowKey:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[_FakeRowKey] = []
        self.added_rows: list[list[str | Text]] = []
        self.cursor_coordinate = (0, 0)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def clear(self) -> None:
        self.rows = []
        self.added_rows = []

    def add_row(self, *row: str | Text, key: str) -> None:
        self.rows.append(_FakeRowKey(key))
        self.added_rows.append(list(row))

    def move_cursor(self, row: int) -> None:
        self.cursor_coordinate = (row, 0)


class _FakeStatus:
    def __init__(self) -> None:
        self.text = ""

    def update(self, text: str) -> None:
        self.text = text


def _render(app: ZeusApp, monkeypatch) -> tuple[_FakeTable, _FakeStatus]:
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
    return table, status


def test_is_hoplite_session_for_requires_role_owner_and_phalanx() -> None:
    agent = _agent(agent_id="polemarch-1")

    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ) is True

    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="other", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="polemarch-1", phalanx_id=""),
    ) is False


def test_render_agent_table_shows_literal_phalanx_label_for_polemarch(monkeypatch) -> None:
    app = ZeusApp()
    polemarch = _agent(agent_id="polemarch-1", role="polemarch")
    polemarch.tmux_sessions = [
        _tmux(name="h1", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
        _tmux(name="h2", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
        _tmux(name="h3", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ]
    app.agents = [polemarch]

    table, _ = _render(app, monkeypatch)

    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    name_idx = cols.index("Name")
    name_cell = table.added_rows[0][name_idx]
    assert isinstance(name_cell, Text)
    assert name_cell.plain == "⌁ polemarch [phalanx: 3]"


def test_render_agent_table_shows_triple_marker_for_god(monkeypatch) -> None:
    app = ZeusApp()
    god = _agent(agent_id="god-1", role="god")
    god.name = "oracle"
    app.agents = [god]

    table, _ = _render(app, monkeypatch)

    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    name_idx = cols.index("Name")
    name_cell = table.added_rows[0][name_idx]
    assert isinstance(name_cell, Text)
    assert name_cell.plain == "⌁⌁⌁ oracle"


def test_render_agent_table_requires_explicit_polemarch_role_for_label(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent(agent_id="polemarch-1", role="")
    agent.tmux_sessions = [
        _tmux(name="h1", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ]
    app.agents = [agent]

    table, _ = _render(app, monkeypatch)

    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    name_idx = cols.index("Name")
    name_cell = table.added_rows[0][name_idx]
    assert isinstance(name_cell, Text)
    assert name_cell.plain == "polemarch"


def test_render_agent_table_lists_hoplites_with_dagger_prefix(monkeypatch) -> None:
    app = ZeusApp()
    polemarch = _agent(agent_id="polemarch-1", role="polemarch")
    polemarch.tmux_sessions = [
        _tmux(name="h1", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ]
    app.agents = [polemarch]

    table, _ = _render(app, monkeypatch)

    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    name_idx = cols.index("Name")
    tmux_name_cell = table.added_rows[1][name_idx]
    assert isinstance(tmux_name_cell, str)
    assert tmux_name_cell == "  └ 🗡 h1"


def test_render_tmux_elapsed_uses_same_format_as_agent_elapsed(monkeypatch) -> None:
    app = ZeusApp()
    polemarch = _agent(agent_id="polemarch-1", role="polemarch")
    polemarch.tmux_sessions = [
        _tmux(name="h1", role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ]
    app.agents = [polemarch]

    table, _ = _render(app, monkeypatch)

    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    elapsed_idx = cols.index("Elapsed")
    tmux_elapsed_cell = table.added_rows[1][elapsed_idx]
    assert isinstance(tmux_elapsed_cell, str)
    assert tmux_elapsed_cell == "0s"
