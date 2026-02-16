"""Tests for kill confirmation dialog safety."""

from types import SimpleNamespace

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
