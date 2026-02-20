"""Backward-compat wrapper around the generic agent bus inbox."""

from __future__ import annotations

from .agent_bus import enqueue_agent_bus_message, sanitize_agent_id


def enqueue_hoplite_inbox_message(
    agent_id: str,
    message: str,
    *,
    message_id: str = "",
    source_name: str = "",
    source_agent_id: str = "",
) -> bool:
    return enqueue_agent_bus_message(
        sanitize_agent_id(agent_id),
        message,
        message_id=message_id,
        source_name=source_name,
        source_agent_id=source_agent_id,
        deliver_as="followUp",
    )
