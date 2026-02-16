"""Tests for direct-summary queue behavior."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import ConfirmDirectMessageScreen
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
    app._dependency_missing_polls = {}
    return app


def test_do_enqueue_direct_queues_to_selected_target(monkeypatch) -> None:
    app = _new_app()
    target = _agent("target", 2)
    app.agents = [target]

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    app.do_enqueue_direct("source", app._agent_key(target), "hello")

    assert len(sent) == 4

    socket, args = sent[0]
    assert socket == target.socket
    assert args == ("send-text", "--match", f"id:{target.kitty_id}", "hello")

    queue_socket, queue_args = sent[1]
    assert queue_socket == target.socket
    assert queue_args == ("send-text", "--match", f"id:{target.kitty_id}", "\x1b[13;3u")

    clear_socket_1, clear_args_1 = sent[2]
    assert clear_socket_1 == target.socket
    assert clear_args_1 == ("send-text", "--match", f"id:{target.kitty_id}", "\x03")

    clear_socket_2, clear_args_2 = sent[3]
    assert clear_socket_2 == target.socket
    assert clear_args_2 == ("send-text", "--match", f"id:{target.kitty_id}", "\x15")

    assert notices[-1] == "Message from source queued to target"


def test_do_enqueue_direct_strips_nul_bytes_before_queueing(monkeypatch) -> None:
    app = _new_app()
    target = _agent("target", 2)
    app.agents = [target]

    sent = capture_kitty_cmd(monkeypatch)

    app.do_enqueue_direct("source", app._agent_key(target), "hi\x00there")

    assert sent[0][1] == ("send-text", "--match", f"id:{target.kitty_id}", "hithere")


def test_do_enqueue_direct_normalizes_crlf_before_queueing(monkeypatch) -> None:
    app = _new_app()
    target = _agent("target", 2)
    app.agents = [target]

    sent = capture_kitty_cmd(monkeypatch)

    app.do_enqueue_direct("source", app._agent_key(target), "a\r\nb\r\nc\r")

    assert sent[0][1] == (
        "send-text",
        "--match",
        f"id:{target.kitty_id}",
        "a\nb\nc\n",
    )


def test_do_enqueue_direct_unpauses_paused_target(monkeypatch) -> None:
    app = _new_app()
    target = _agent("target", 2)
    app.agents = [target]
    app._agent_priorities = {"target": 4}

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    app.do_enqueue_direct("source", app._agent_key(target), "hello")

    assert len(sent) == 4
    assert app._agent_priorities.get(target.name, 3) == 3
    assert notices[-1] == "Message from source queued to target"


def test_do_enqueue_direct_skips_blocked_target(monkeypatch) -> None:
    app = _new_app()
    source = _agent("source", 1)
    target = _agent("target", 2)
    app.agents = [source, target]
    app._agent_dependencies = {
        app._agent_dependency_key(target): app._agent_dependency_key(source)
    }

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)

    app.do_enqueue_direct("source", app._agent_key(target), "hello")

    assert sent == []
    assert notices[-1] == "Target is no longer active"


def test_direct_recipients_include_paused_and_source_blocked_dependents() -> None:
    app = _new_app()
    source = _agent("source", 1)
    blocked_by_source = _agent("blocked-by-source", 2)
    blocked_by_other = _agent("blocked-by-other", 3)
    other_blocker = _agent("other-blocker", 4)
    active = _agent("active", 5)

    app.agents = [source, blocked_by_source, blocked_by_other, other_blocker, active]
    app._agent_dependencies = {
        app._agent_dependency_key(blocked_by_source): app._agent_dependency_key(source),
        app._agent_dependency_key(blocked_by_other): app._agent_dependency_key(other_blocker),
    }
    app._agent_priorities[other_blocker.name] = 4

    recipients = app._direct_recipients(app._agent_key(source))

    assert [agent.name for agent in recipients] == [
        "blocked-by-source",
        "other-blocker",
        "active",
    ]


def test_do_enqueue_direct_allows_blocked_target_from_blocker_and_clears_dependency(
    monkeypatch,
) -> None:
    app = _new_app()
    source = _agent("source", 1)
    target = _agent("target", 2)
    source_key = app._agent_key(source)
    target_key = app._agent_key(target)
    target_dep_key = app._agent_dependency_key(target)

    app.agents = [source, target]
    app._agent_dependencies[target_dep_key] = app._agent_dependency_key(source)

    sent = capture_kitty_cmd(monkeypatch)
    notices = capture_notify(app, monkeypatch)
    saves: list[dict[str, str]] = []
    renders: list[bool] = []

    monkeypatch.setattr(
        app,
        "_save_agent_dependencies",
        lambda: saves.append(dict(app._agent_dependencies)),
    )
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    app.do_enqueue_direct("source", target_key, "hello", source_key=source_key)

    assert len(sent) == 4
    assert target_dep_key not in app._agent_dependencies
    assert saves == [{}]
    assert renders == [True]
    assert notices[-1] == "Message from source queued to target; dependency cleared"


def test_show_direct_preview_includes_blocked_target_of_source(monkeypatch) -> None:
    app = _new_app()
    source = _agent("source", 1)
    blocked = _agent("blocked", 2)
    source_key = app._agent_key(source)
    blocked_key = app._agent_key(blocked)

    app.agents = [source, blocked]
    app._agent_dependencies = {
        app._agent_dependency_key(blocked): app._agent_dependency_key(source)
    }

    job_id = 7
    app._broadcast_active_job = job_id

    pushed: list[object] = []
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(app, "_dismiss_broadcast_preparing_screen", lambda: None)

    app._show_direct_preview(
        job_id,
        "source",
        [blocked_key],
        "msg",
        source_key=source_key,
    )

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, ConfirmDirectMessageScreen)
    assert screen.target_options == [("blocked", blocked_key)]


def test_show_direct_preview_uses_selection_from_preparing_dialog(monkeypatch) -> None:
    app = _new_app()
    a1 = _agent("alpha", 1)
    a2 = _agent("beta", 2)
    app.agents = [a1, a2]

    job_id = 7
    app._broadcast_active_job = job_id
    selected_key = app._agent_key(a2)
    app._prepare_target_selection[job_id] = selected_key

    pushed: list[object] = []
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(app, "_dismiss_broadcast_preparing_screen", lambda: None)

    app._show_direct_preview(
        job_id,
        "source",
        [app._agent_key(a1), app._agent_key(a2)],
        "msg",
    )

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, ConfirmDirectMessageScreen)
    assert screen.initial_target_key == selected_key
