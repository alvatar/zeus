"""Tests for Stygian Hippeus tmux backend."""

from __future__ import annotations

import subprocess

from rich.text import Text

import zeus.stygian_hippeus as stygian_backend
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


def _stygian_agent(name: str = "shadow", *, agent_id: str = "agent-stygian") -> AgentWindow:
    return AgentWindow(
        kitty_id=0,
        socket="",
        name=name,
        pid=123,
        kitty_pid=0,
        cwd="/tmp/project",
        agent_id=agent_id,
        state=State.IDLE,
        backend=stygian_backend.STYGIAN_AGENT_BACKEND,
        tmux_session="stygian-agent",
    )


def test_discover_stygian_agents_builds_rows_and_filters_tmux_view() -> None:
    stygian_sess = TmuxSession(
        name="stygian-agent",
        command="pi",
        cwd="/tmp/project",
        pane_pid=222,
        agent_id="agent-stygian",
        role="hippeus",
        backend=stygian_backend.STYGIAN_TMUX_BACKEND_TAG,
        display_name="shadow",
        session_path="/tmp/session.jsonl",
    )
    viewer = TmuxSession(name="viewer", command="bash", cwd="/tmp/project")

    stygian_agents, remaining = stygian_backend.discover_stygian_agents(
        [stygian_sess, viewer],
        name_overrides={stygian_backend.stygian_agent_row_key("agent-stygian"): "renamed"},
    )

    assert [a.name for a in stygian_agents] == ["renamed"]
    assert stygian_agents[0].backend == stygian_backend.STYGIAN_AGENT_BACKEND
    assert stygian_agents[0].tmux_session == "stygian-agent"
    assert stygian_agents[0].session_path == "/tmp/session.jsonl"
    assert remaining == [viewer]


def test_launch_stygian_hippeus_creates_tmux_session_and_sets_metadata(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(stygian_backend.subprocess, "run", _run)
    monkeypatch.setattr(
        stygian_backend,
        "make_new_session_path",
        lambda _cwd: "/tmp/stygian-session.jsonl",
    )

    session_name, session_path = stygian_backend.launch_stygian_hippeus(
        name="shadow",
        directory="/tmp/project",
        agent_id="agent-1234",
    )

    assert session_name == "stygian-agent-12"
    assert session_path == "/tmp/stygian-session.jsonl"
    assert commands[0][:6] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "stygian-agent-12",
        "-c",
    ]
    assert commands[0][6] == "/tmp/project"
    assert "ZEUS_AGENT_NAME=shadow" in commands[0][7]
    assert "ZEUS_AGENT_ID=agent-1234" in commands[0][7]
    assert "ZEUS_ROLE=hippeus" in commands[0][7]
    assert "ZEUS_SESSION_PATH=/tmp/stygian-session.jsonl" in commands[0][7]

    option_commands = [cmd for cmd in commands[1:] if cmd[:3] == ["tmux", "set-option", "-t"]]
    assert [cmd[4] for cmd in option_commands] == [
        "@zeus_backend",
        "@zeus_agent",
        "@zeus_role",
        "@zeus_name",
        "@zeus_session_path",
    ]


def test_promote_hoplite_to_stygian_hippeus_sets_expected_tmux_options(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(stygian_backend.subprocess, "run", _run)

    sess = TmuxSession(
        name="hoplite-a",
        command="",
        cwd="/tmp/project",
        owner_id="polemarch-1",
        role="hoplite",
        phalanx_id="phalanx-polemarch-1",
        agent_id="hoplite-1",
        session_path="/tmp/hoplite-session.jsonl",
    )

    ok, detail = stygian_backend.promote_hoplite_to_stygian_hippeus(sess)

    assert ok is True
    assert detail == ""
    assert commands == [
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_backend", "stygian-hippeus"],
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_agent", "hoplite-1"],
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_role", "hippeus"],
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_name", "hoplite-a"],
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_owner", ""],
        ["tmux", "set-option", "-t", "hoplite-a", "@zeus_phalanx", ""],
        [
            "tmux",
            "set-option",
            "-t",
            "hoplite-a",
            "@zeus_session_path",
            "/tmp/hoplite-session.jsonl",
        ],
    ]


def test_promote_hoplite_to_stygian_hippeus_requires_agent_id() -> None:
    sess = TmuxSession(
        name="hoplite-a",
        command="",
        cwd="/tmp/project",
        role="hoplite",
    )

    ok, detail = stygian_backend.promote_hoplite_to_stygian_hippeus(sess)

    assert ok is False
    assert detail == "missing hoplite agent id"


def test_capture_and_send_stygian_tmux_commands(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        stdout = "pane text" if command[:3] == ["tmux", "capture-pane", "-t"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(stygian_backend.subprocess, "run", _run)

    text = stygian_backend.capture_stygian_screen_text("stygian-agent", full=True, ansi=True)
    assert text == "pane text"
    assert commands[0] == [
        "tmux",
        "capture-pane",
        "-t",
        "stygian-agent",
        "-p",
        "-e",
        "-S",
        "-",
    ]

    assert stygian_backend.send_stygian_text("stygian-agent", "hello", queue=True) is True
    assert commands[1] == ["tmux", "send-keys", "-t", "stygian-agent", "hello", "M-Enter"]

    assert stygian_backend.send_stygian_escape("stygian-agent") is True
    assert commands[2] == ["tmux", "send-keys", "-t", "stygian-agent", "Escape"]


def test_resolve_stygian_session_path_prefers_tmux_option(monkeypatch) -> None:
    def _run(command: list[str], **_kwargs):
        if command[:4] == ["tmux", "show-options", "-t", "stygian-agent"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="/tmp/option-session.jsonl\n",
                stderr="",
            )
        raise AssertionError("must not query pane command when option exists")

    monkeypatch.setattr(stygian_backend.subprocess, "run", _run)

    path = stygian_backend.resolve_stygian_session_path("stygian-agent")
    assert path == "/tmp/option-session.jsonl"


def test_resolve_stygian_session_path_falls_back_to_start_command(monkeypatch) -> None:
    def _run(command: list[str], **_kwargs):
        if command[:4] == ["tmux", "show-options", "-t", "stygian-agent"]:
            return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")
        if command[:4] == ["tmux", "list-panes", "-t", "stygian-agent"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "ZEUS_AGENT_NAME=shadow ZEUS_SESSION_PATH=/tmp/fallback.jsonl "
                    "exec pi --session /tmp/fallback.jsonl\n"
                ),
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(stygian_backend.subprocess, "run", _run)

    path = stygian_backend.resolve_stygian_session_path("stygian-agent")
    assert path == "/tmp/fallback.jsonl"


def test_app_agent_key_and_dispatch_for_stygian_backend(monkeypatch) -> None:
    app = ZeusApp()
    agent = _stygian_agent()

    assert app._agent_key(agent) == "stygian:agent-stygian"

    sends: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.send_stygian_text",
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
        ("stygian-agent", "hello", False),
        ("stygian-agent", "hello", True),
    ]


def test_stygian_agent_stop_and_kill_use_tmux_backend(monkeypatch) -> None:
    app = ZeusApp()
    agent = _stygian_agent("shadow")

    notices: list[str] = []
    polled: list[bool] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))
    monkeypatch.setattr(app, "_has_blocking_modal_open", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr("zeus.dashboard.app.send_stygian_escape", lambda _sess: True)
    monkeypatch.setattr("zeus.dashboard.app.kill_stygian_session", lambda _sess: (True, ""))

    app._send_stop_to_selected_agent()
    app.do_kill_agent(agent)

    assert notices[0] == "ESC → shadow"
    assert notices[1] == "Killed: shadow"
    assert polled == [True]


def test_stygian_agents_render_with_icon_and_normal_row_style(monkeypatch) -> None:
    app = ZeusApp()
    table = _FakeTable()
    status = _FakeStatus()

    agent = _stygian_agent("shadow")
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
    assert name_cell.plain.startswith("◆ shadow")
    assert name_cell.style == ""
