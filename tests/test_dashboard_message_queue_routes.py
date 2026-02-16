"""Tests for queue routing and dedupe behavior."""

from __future__ import annotations

from pathlib import Path

import zeus.message_queue as mq
import zeus.message_receipts as receipts
from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, TmuxSession


def _agent(name: str, kitty_id: int, *, agent_id: str) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mq, "MESSAGE_QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr(receipts, "MESSAGE_RECEIPTS_FILE", tmp_path / "receipts.json")


def test_drain_message_queue_routes_phalanx_to_hoplite_tmux_sessions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    app = ZeusApp()

    polemarch = _agent("polemarch", 1, agent_id="polemarch-1")
    polemarch.tmux_sessions = [
        TmuxSession(
            name="hoplite-a",
            command="pi",
            cwd="/tmp/project",
            role="hoplite",
            owner_id="polemarch-1",
            phalanx_id="phalanx-polemarch-1",
            # Real-world tmux session env can inherit owner id.
            env_agent_id="polemarch-1",
            # Dedicated hoplite identity for delivery routing.
            agent_id="hoplite-1",
        ),
        TmuxSession(
            name="hoplite-b",
            command="pi",
            cwd="/tmp/project",
            role="hoplite",
            owner_id="polemarch-1",
            phalanx_id="phalanx-polemarch-1",
            env_agent_id="polemarch-1",
            agent_id="hoplite-2",
        ),
    ]

    app.agents = [polemarch]
    app._message_receipts = {}

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app,
        "_dispatch_tmux_text",
        lambda sess, text, queue: calls.append((sess, text)) or True,
    )

    envelope = mq.OutboundEnvelope.new(
        source_name="polemarch",
        source_agent_id="polemarch-1",
        target_kind="phalanx",
        target_ref="phalanx-polemarch-1",
        target_owner_id="polemarch-1",
        message="hello",
    )
    mq.enqueue_envelope(envelope)

    app._drain_message_queue()

    assert sorted(calls) == [("hoplite-a", "hello"), ("hoplite-b", "hello")]
    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []


def test_drain_message_queue_routes_hoplite_by_session_agent_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    app = ZeusApp()

    polemarch = _agent("polemarch", 1, agent_id="polemarch-1")
    polemarch.tmux_sessions = [
        TmuxSession(
            name="hoplite-a",
            command="ZEUS_AGENT_ID=hoplite-1 exec pi",
            cwd="/tmp/project",
            role="hoplite",
            owner_id="polemarch-1",
            phalanx_id="phalanx-polemarch-1",
            env_agent_id="polemarch-1",
            agent_id="hoplite-1",
        )
    ]
    app.agents = [polemarch]
    app._message_receipts = {}

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        app,
        "_dispatch_tmux_text",
        lambda sess, text, queue: calls.append((sess, text)) or True,
    )

    envelope = mq.OutboundEnvelope.new(
        source_name="polemarch",
        source_agent_id="polemarch-1",
        target_kind="hoplite",
        target_ref="hoplite-1",
        target_owner_id="polemarch-1",
        message="hello-hoplite",
    )
    mq.enqueue_envelope(envelope)

    app._drain_message_queue()

    assert calls == [("hoplite-a", "hello-hoplite")]
    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []


def test_drain_message_queue_dedupes_same_message_id_per_recipient(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    app = ZeusApp()

    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [target]
    app._message_receipts = {}

    sends: list[str] = []
    monkeypatch.setattr(
        app,
        "_queue_text_to_agent",
        lambda agent, text: sends.append(text) or True,
    )

    env1 = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="hello",
    )
    env1.id = "msg-1"
    mq.enqueue_envelope(env1)
    app._drain_message_queue()

    env2 = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="hello",
    )
    env2.id = "msg-1"
    mq.enqueue_envelope(env2)
    app._drain_message_queue()

    assert sends == ["hello"]
    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []
