"""Tests for dashboard agent notes behavior helpers."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int, agent_id: str = "") -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def test_agent_notes_key_prefers_agent_id() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    assert app._agent_notes_key(agent) == "agent-1"


def test_has_note_for_agent_checks_stored_text() -> None:
    app = ZeusApp()
    agent = _agent("x", 1, agent_id="agent-1")
    app._agent_notes = {"agent-1": "next: fix parser"}

    assert app._has_note_for_agent(agent) is True
