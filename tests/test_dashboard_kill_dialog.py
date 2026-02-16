"""Tests for kill confirmation dialog safety."""

import subprocess
from types import SimpleNamespace

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import ConfirmKillScreen, ConfirmKillTmuxScreen
from zeus.models import AgentWindow, TmuxSession


class _Pressed:
    def __init__(self, button_id: str) -> None:
        self.button = SimpleNamespace(id=button_id)
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _agent() -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="agent",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )


def _tmux() -> TmuxSession:
    return TmuxSession(
        name="sess",
        command="pi",
        cwd="/tmp/project",
    )


def test_confirm_kill_no_button_does_not_kill(monkeypatch) -> None:
    screen = ConfirmKillScreen(_agent())

    killed: list[str] = []

    class _ZeusStub:
        def do_kill_agent(self, agent: AgentWindow) -> None:
            killed.append(agent.name)

    monkeypatch.setattr(ConfirmKillScreen, "zeus", property(lambda self: _ZeusStub()))

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    event = _Pressed("no-btn")
    screen.on_button_pressed(event)  # type: ignore[arg-type]

    assert killed == []
    assert dismissed == [True]
    assert event.stopped is True


def test_confirm_kill_tmux_no_button_does_not_kill(monkeypatch) -> None:
    screen = ConfirmKillTmuxScreen(_tmux())

    killed: list[str] = []

    class _ZeusStub:
        def do_kill_tmux(self, sess: TmuxSession) -> None:
            killed.append(sess.name)

    monkeypatch.setattr(ConfirmKillTmuxScreen, "zeus", property(lambda self: _ZeusStub()))

    dismissed: list[bool] = []
    monkeypatch.setattr(screen, "dismiss", lambda: dismissed.append(True))

    event = _Pressed("no-btn")
    screen.on_button_pressed(event)  # type: ignore[arg-type]

    assert killed == []
    assert dismissed == [True]
    assert event.stopped is True


def test_confirm_kill_screens_do_not_force_enter_handler() -> None:
    assert "on_key" not in ConfirmKillScreen.__dict__
    assert "on_key" not in ConfirmKillTmuxScreen.__dict__


def test_action_kill_tmux_session_requires_tmux_selection(monkeypatch) -> None:
    app = ZeusApp()
    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: None)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))

    app.action_kill_tmux_session()

    assert notices[-1] == "Select a tmux row to kill session"


def test_do_kill_tmux_session_runs_kill_session(monkeypatch) -> None:
    app = ZeusApp()
    sess = _tmux()

    notices: list[str] = []
    polled: list[bool] = []
    killed_pids: list[int] = []
    commands: list[list[str]] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))
    monkeypatch.setattr(app, "_get_tmux_client_pid", lambda _name: None)
    monkeypatch.setattr("zeus.dashboard.app.kill_pid", lambda pid: killed_pids.append(pid))

    def _run(command: list[str], **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("zeus.dashboard.app.subprocess.run", _run)

    app.do_kill_tmux_session(sess)

    assert ["tmux", "kill-session", "-t", sess.name] in commands
    assert notices[-1] == f"Killed tmux: {sess.name}"
    assert polled == [True]
    assert killed_pids == []
