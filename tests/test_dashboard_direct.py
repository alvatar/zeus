"""Tests for direct-summary queue behavior."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import ConfirmDirectMessageScreen
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int, socket: str = "/tmp/kitty-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket=socket,
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def test_do_enqueue_direct_queues_to_selected_target(monkeypatch) -> None:
    app = ZeusApp()
    target = _agent("target", 2)
    app.agents = [target]

    sent: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.kitty_cmd",
        lambda socket, *args, timeout=3: sent.append((socket, args)) or "",
    )

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.do_enqueue_direct("source", app._agent_key(target), "hello")

    assert len(sent) == 1
    socket, args = sent[0]
    assert socket == target.socket
    assert args[:3] == ("send-text", "--match", f"id:{target.kitty_id}")
    assert args[3].startswith("hello")
    assert args[3].endswith("\x1b[13;3u\x15")
    assert notices[-1] == "Summary from source queued to target"


def test_do_enqueue_direct_skips_paused_target(monkeypatch) -> None:
    app = ZeusApp()
    target = _agent("target", 2)
    app.agents = [target]
    app._agent_priorities = {"target": 4}

    sent: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.kitty_cmd",
        lambda socket, *args, timeout=3: sent.append((socket, args)) or "",
    )

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.do_enqueue_direct("source", app._agent_key(target), "hello")

    assert sent == []
    assert notices[-1] == "Target is no longer active"


def test_show_direct_preview_uses_selection_from_preparing_dialog(monkeypatch) -> None:
    app = ZeusApp()
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
