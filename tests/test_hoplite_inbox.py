from __future__ import annotations

import zeus.hoplite_inbox as inbox


def test_enqueue_hoplite_inbox_message_forwards_to_agent_bus(monkeypatch) -> None:
    calls: list[tuple[str, str, str, str, str, str]] = []

    monkeypatch.setattr(
        inbox,
        "enqueue_agent_bus_message",
        lambda agent_id, message, message_id="", source_name="", source_agent_id="", deliver_as="followUp": calls.append(
            (agent_id, message, message_id, source_name, source_agent_id, deliver_as)
        )
        or True,
    )

    ok = inbox.enqueue_hoplite_inbox_message(
        "hoplite-1",
        "hello",
        message_id="msg-1",
        source_name="polemarch",
        source_agent_id="agent-polemarch",
    )

    assert ok is True
    assert calls == [
        (
            "hoplite-1",
            "hello",
            "msg-1",
            "polemarch",
            "agent-polemarch",
            "followUp",
        )
    ]


def test_enqueue_hoplite_inbox_message_sanitizes_agent_id(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        inbox,
        "enqueue_agent_bus_message",
        lambda agent_id, *_args, **_kwargs: calls.append(agent_id) or True,
    )

    inbox.enqueue_hoplite_inbox_message("../hoplite-1", "payload")

    assert calls == ["hoplite-1"]
