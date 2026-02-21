"""Tests for outbound queue helper behavior."""

from pathlib import Path

from zeus.dashboard.app import ZeusApp
from zeus.message_queue import OutboundEnvelope
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


def test_enqueue_outbound_agent_message_records_delivery_mode_and_history(
    monkeypatch,
) -> None:
    app = ZeusApp()
    agent = _agent("target", 2, agent_id="a" * 32)

    queued: list[OutboundEnvelope] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.enqueue_envelope",
        lambda envelope: queued.append(envelope) or Path("/tmp/queue.json"),
    )

    history: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.append_history",
        lambda key, text: history.append((key, text)) or [text],
    )

    ok = app._enqueue_outbound_agent_message(
        agent,
        "hello",
        source_name="oracle",
        delivery_mode="followUp",
    )

    assert ok is True
    assert len(queued) == 1
    envelope = queued[0]
    assert envelope.delivery_mode == "followUp"
    assert envelope.target_agent_id == "a" * 32
    assert envelope.target_name == "target"
    assert envelope.message == "hello"
    assert history == [("agent:target", "hello")]


def test_enqueue_outbound_agent_message_rejects_missing_target_agent_id(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("target", 2)

    queued: list[OutboundEnvelope] = []
    monkeypatch.setattr(
        "zeus.dashboard.app.enqueue_envelope",
        lambda envelope: queued.append(envelope) or Path("/tmp/queue.json"),
    )

    ok = app._enqueue_outbound_agent_message(
        agent,
        "hello",
        source_name="oracle",
        delivery_mode="steer",
    )

    assert ok is False
    assert queued == []
