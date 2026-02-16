"""Tests for table-triggered Hippeus message dialog helpers."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import AgentMessageScreen
from zeus.models import AgentWindow
from tests.helpers import capture_kitty_cmd, capture_notify


def _agent(name: str, kitty_id: int, socket: str = "/tmp/kitty-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket=socket,
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def _new_app() -> ZeusApp:
    app = ZeusApp()
    app._agent_dependencies = {}
    app._agent_priorities = {}
    return app


def test_action_agent_message_pushes_message_screen(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_agent_message()

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, AgentMessageScreen)
    assert screen.agent is agent


def test_do_send_agent_message_dispatches_enter(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app.agents = [agent]

    sent = capture_kitty_cmd(monkeypatch)

    ok = app.do_send_agent_message(agent, "hello")

    assert ok is True
    assert sent == [
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "hello\r"))
    ]


def test_do_queue_agent_message_uses_interact_ctrl_w_sequence(monkeypatch) -> None:
    app = _new_app()
    agent = _agent("alpha", 1)
    app.agents = [agent]

    sent = capture_kitty_cmd(monkeypatch)

    ok = app.do_queue_agent_message(agent, "hello")

    assert ok is True
    assert sent == [
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "hello")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x1b[13;3u")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x15")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x15")),
    ]


def test_message_dialog_send_rejects_paused_or_blocked_target(monkeypatch) -> None:
    app = _new_app()
    source = _agent("source", 1)
    paused = _agent("paused", 2)
    blocked = _agent("blocked", 3)
    blocker = _agent("blocker", 4)

    app.agents = [source, paused, blocked, blocker]
    app._agent_priorities[paused.name] = 4
    app._agent_dependencies[app._agent_dependency_key(blocked)] = app._agent_dependency_key(
        blocker
    )

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    assert app.do_send_agent_message(paused, "hello") is False
    assert notices[-1] == "Hippeus is PAUSED (priority 4); input disabled"

    assert app.do_queue_agent_message(blocked, "hello") is False
    assert notices[-1] == "Hippeus is BLOCKED by dependency; input disabled"

    assert sent == []


def test_app_ctrl_s_routes_to_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = AgentMessageScreen(_agent("alpha", 1))

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_send", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_send_interact()

    assert called == [True]


def test_app_ctrl_w_routes_to_message_modal_when_open(monkeypatch) -> None:
    app = _new_app()
    modal = AgentMessageScreen(_agent("alpha", 1))

    called: list[bool] = []
    monkeypatch.setattr(modal, "action_queue", lambda: called.append(True))
    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(ZeusApp, "screen", property(lambda self: modal))

    app.action_queue_interact()

    assert called == [True]
