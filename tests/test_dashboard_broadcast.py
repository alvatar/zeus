"""Tests for broadcast-summary helpers."""

from zeus.dashboard.app import ZeusApp, _build_broadcast_message
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


def test_build_broadcast_message_adds_prefix_and_summary() -> None:
    msg = _build_broadcast_message("Done: migrated API and waiting on schema review.")
    assert msg.startswith(
        "This is a broadcast message. Read it and decide whether "
        "this is pertaining your work or not."
    )
    assert msg.endswith("Done: migrated API and waiting on schema review.")


def test_broadcast_recipients_exclude_source_and_paused() -> None:
    app = ZeusApp()
    source = _agent("source", 1)
    active = _agent("active", 2)
    paused = _agent("paused", 3)

    app.agents = [source, active, paused]
    app._agent_priorities = {"paused": 4}

    recipients = app._broadcast_recipients(app._agent_key(source))
    assert [a.name for a in recipients] == ["active"]
