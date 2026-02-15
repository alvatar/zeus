"""Tests for queue-send helper variants."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow
from tests.helpers import capture_kitty_cmd


def _agent(name: str, kitty_id: int) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def test_queue_text_to_agent_interact_keeps_ctrl_w_clear_sequence(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("target", 2)

    sent = capture_kitty_cmd(monkeypatch)

    app._queue_text_to_agent_interact(agent, "hello")

    assert sent == [
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "hello")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x1b[13;3u")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x15")),
        (agent.socket, ("send-text", "--match", f"id:{agent.kitty_id}", "\x15")),
    ]
