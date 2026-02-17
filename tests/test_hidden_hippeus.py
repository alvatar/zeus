"""Tests for hidden Hippeus tmux backend."""

from __future__ import annotations

import subprocess

from rich.text import Text

import zeus.hidden_hippeus as hidden_backend
from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, State, TmuxSession


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


def _hidden_agent(name: str = "shadow", *, agent_id: str = "agent-hidden") -> AgentWindow:
    return AgentWindow(
        kitty_id=0,
        socket="",
        name=name,
        pid=123,
        kitty_pid=0,
        cwd="/tmp/project",
        agent_id=agent_id,
        state=State.IDLE,
        backend=hidden_backend.HIDDEN_AGENT_BACKEND,
        tmux_session="hidden-agent",
    )


def test_discover_hidden_agents_builds_rows_and_filters_tmux_view() -> None:
    hidden_sess = TmuxSession(
        name="hidden-agent",
        command="pi",
        cwd="/tmp/project",
        pane_pid=222,
        agent_id="agent-hidden",
        role="hippeus",
        backend=hidden_backend.HIDDEN_TMUX_BACKEND_TAG,
        display_name="shadow",
        session_path="/tmp/session.jsonl",
    )
    viewer = TmuxSession(name="viewer", command="bash", cwd="/tmp/project")

    hidden_agents, remaining = hidden_backend.discover_hidden_agents(
        [hidden_sess, viewer],
        name_overrides={hidden_backend.hidden_agent_row_key("agent-hidden"): "renamed"},
    )

    assert [a.name for a in hidden_agents] == ["renamed"]
    assert hidden_agents[0].backend == hidden_backend.HIDDEN_AGENT_BACKEND
    assert hidden_agents[0].tmux_session == "hidden-agent"
    assert hidden_agents[0].session_path == "/tmp/session.jsonl"
    assert remaining == [viewer]


def test_launch_hidden_hippeus_creates_tmux_session_and_sets_metadata(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(hidden_backend.subprocess, "run", _run)
    monkeypatch.setattr(
        hidden_backend,
        "make_new_session_path",
        lambda _cwd: "/tmp/hidden-session.jsonl",
    )

    session_name, session_path = hidden_backend.launch_hidden_hippeus(
        name="shadow",
        directory="/tmp/project",
        agent_id="agent-1234",
    )

    assert session_name == "hidden-agent-12"
    assert session_path == "/tmp/hidden-session.jsonl"
    assert commands[0][:6] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "hidden-agent-12",
        "-c",
    ]
    assert commands[0][6] == "/tmp/project"
    assert "ZEUS_AGENT_NAME=shadow" in commands[0][7]
    assert "ZEUS_AGENT_ID=agent-1234" in commands[0][7]
    assert "ZEUS_ROLE=hippeus" in commands[0][7]
    assert "ZEUS_SESSION_PATH=/tmp/hidden-session.jsonl" in commands[0][7]

    option_commands = [cmd for cmd in commands[1:] if cmd[:3] == ["tmux", "set-option", "-t"]]
    assert [cmd[4] for cmd in option_commands] == [
        "@zeus_backend",
        "@zeus_agent",
        "@zeus_role",
        "@zeus_name",
        "@zeus_session_path",
    ]


def test_capture_and_send_hidden_tmux_commands(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        stdout = "pane text" if command[:3] == ["tmux", "capture-pane", "-t"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(hidden_backend.subprocess, "run", _run)

    text = hidden_backend.capture_hidden_screen_text("hidden-agent", full=True, ansi=True)
    assert text == "pane text"
    assert commands[0] == [
        "tmux",
        "capture-pane",
        "-t",
        "hidden-agent",
        "-p",
        "-e",
        "-S",
        "-",
    ]

    assert hidden_backend.send_hidden_text("hidden-agent", "hello", queue=True) is True
    assert commands[1] == ["tmux", "send-keys", "-t", "hidden-agent", "hello", "M-Enter"]

    assert hidden_backend.send_hidden_escape("hidden-agent") is True
    assert commands[2] == ["tmux", "send-keys", "-t", "hidden-agent", "Escape"]


def test_app_agent_key_and_dispatch_for_hidden_backend(monkeypatch) -> None:
    app = ZeusApp()
    agent = _hidden_agent()

    assert app._agent_key(agent) == "hidden:agent-hidden"

    sends: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.send_hidden_text",
        lambda sess, text, queue: sends.append((sess, text, queue)) or True,
    )
    monkeypatch.setattr("zeus.dashboard.app.append_history", lambda *_args, **_kwargs: None)

    ok_send = app._dispatch_agent_text(agent, "hello")
    ok_queue = app._dispatch_agent_text(
        agent,
        "hello",
        queue_sequence=app._QUEUE_SEQUENCE_DEFAULT,
    )

    assert ok_send is True
    assert ok_queue is True
    assert sends == [
        ("hidden-agent", "hello", False),
        ("hidden-agent", "hello", True),
    ]


def test_hidden_agent_stop_and_kill_use_tmux_backend(monkeypatch) -> None:
    app = ZeusApp()
    agent = _hidden_agent("shadow")

    notices: list[str] = []
    polled: list[bool] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))
    monkeypatch.setattr(app, "_has_blocking_modal_open", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr("zeus.dashboard.app.send_hidden_escape", lambda _sess: True)
    monkeypatch.setattr("zeus.dashboard.app.kill_hidden_session", lambda _sess: (True, ""))

    app._send_stop_to_selected_agent()
    app.do_kill_agent(agent)

    assert notices[0] == "ESC → shadow"
    assert notices[1] == "Killed: shadow"
    assert polled == [True]


def test_hidden_agents_render_with_viewer_icon_and_gray_row(monkeypatch) -> None:
    app = ZeusApp()
    table = _FakeTable()
    status = _FakeStatus()

    agent = _hidden_agent("shadow")
    app.agents = [agent]

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

    row_key = app._agent_key(agent)
    cols = app._SPLIT_COLUMNS if app._split_mode else app._FULL_COLUMNS
    name_idx = cols.index("Name")
    name_cell = table.row_cells[row_key][name_idx]

    assert isinstance(name_cell, Text)
    assert name_cell.plain.startswith("⬡ shadow")
    assert name_cell.style == "#666666"
