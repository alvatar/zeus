"""Tests for queue routing, gating, and ACK behavior."""

from __future__ import annotations

import json
from pathlib import Path

import zeus.agent_bus as bus
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
    monkeypatch.setattr(bus, "AGENT_BUS_INBOX_DIR", tmp_path / "bus" / "inbox")
    monkeypatch.setattr(bus, "AGENT_BUS_RECEIPTS_DIR", tmp_path / "bus" / "receipts")
    monkeypatch.setattr(bus, "AGENT_BUS_CAPS_DIR", tmp_path / "bus" / "caps")
    monkeypatch.setattr(bus, "AGENT_BUS_PROCESSED_DIR", tmp_path / "bus" / "processed")


def _advance_clock(monkeypatch, *, start: float = 100.0, step: float = 2.0) -> None:
    now = {"value": start}

    def _time() -> float:
        now["value"] += step
        return now["value"]

    monkeypatch.setattr("zeus.dashboard.app.time.time", _time)


def _write_capability(tmp_path: Path, agent_id: str, *, updated_at: float = 10_000.0) -> None:
    cap_file = tmp_path / "bus" / "caps" / f"{agent_id}.json"
    cap_file.parent.mkdir(parents=True, exist_ok=True)
    cap_file.write_text(
        json.dumps(
            {
                "agent_id": agent_id,
                "updated_at": updated_at,
                "supports": {"queue_bus": True, "receipt_v1": True},
            }
        )
    )


def _write_accepted_receipt(tmp_path: Path, agent_id: str, message_id: str) -> None:
    receipt_file = tmp_path / "bus" / "receipts" / agent_id / f"{message_id}.json"
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.write_text(
        json.dumps(
            {
                "id": message_id,
                "status": "accepted",
                "accepted_at": 1234.0,
                "agent_id": agent_id,
            }
        )
    )


def test_drain_message_queue_routes_phalanx_via_agent_bus_and_waits_for_receipts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

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
            env_agent_id="polemarch-1",
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

    _write_capability(tmp_path, "hoplite-1")
    _write_capability(tmp_path, "hoplite-2")

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

    files_1 = sorted((tmp_path / "bus" / "inbox" / "hoplite-1" / "new").glob("*.json"))
    files_2 = sorted((tmp_path / "bus" / "inbox" / "hoplite-2" / "new").glob("*.json"))
    assert len(files_1) == 1
    assert len(files_2) == 1
    assert json.loads(files_1[0].read_text())["message"] == "hello"
    assert len(mq.list_new_envelopes()) == 1

    _write_accepted_receipt(tmp_path, "hoplite-1", envelope.id)
    _write_accepted_receipt(tmp_path, "hoplite-2", envelope.id)

    app._drain_message_queue()

    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []


def test_drain_message_queue_hoplite_without_agent_id_is_blocked_with_notice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()

    polemarch = _agent("polemarch", 1, agent_id="polemarch-1")
    polemarch.tmux_sessions = [
        TmuxSession(
            name="hoplite-x",
            command="exec pi",
            cwd="/tmp/project",
            role="hoplite",
            owner_id="polemarch-1",
            phalanx_id="phalanx-polemarch-1",
            env_agent_id="",
            agent_id="",
        )
    ]
    app.agents = [polemarch]
    app._message_receipts = {}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    envelope = mq.OutboundEnvelope.new(
        source_name="polemarch",
        source_agent_id="polemarch-1",
        target_kind="phalanx",
        target_ref="phalanx-polemarch-1",
        target_owner_id="polemarch-1",
        message="fallback",
    )
    mq.enqueue_envelope(envelope)

    app._drain_message_queue()

    assert notices
    assert "Queue blocked:" in notices[-1]
    assert "missing @zeus_agent id" in notices[-1]
    assert len(mq.list_new_envelopes()) == 1
    assert mq.list_inflight_envelopes() == []


def test_drain_message_queue_unresolved_notice_emits_once_for_same_reason(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()
    app.agents = []
    app._message_receipts = {}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    envelope = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="hoplite",
        target_ref="missing-hoplite",
        target_owner_id="polemarch-1",
        message="payload",
    )
    mq.enqueue_envelope(envelope)

    app._drain_message_queue()
    app._drain_message_queue()

    assert len(notices) == 1
    assert "Queue blocked:" in notices[0]


def test_drain_message_queue_drops_stale_unresolved_envelope(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch, start=200_000.0)

    app = ZeusApp()
    app.agents = []
    app._message_receipts = {}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    envelope = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="hoplite",
        target_ref="missing-hoplite",
        target_owner_id="polemarch-1",
        message="payload",
    )
    envelope.created_at = 1.0
    envelope.updated_at = 1.0
    mq.enqueue_envelope(envelope)

    app._drain_message_queue()

    assert notices
    assert "Queue blocked:" in notices[-1]
    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []


def test_drain_message_queue_blocks_when_capability_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()
    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [target]
    app._message_receipts = {}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify_force", lambda message, timeout=3: notices.append(message))

    env = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="wake-up",
    )
    mq.enqueue_envelope(env)

    app._drain_message_queue()

    assert notices
    assert "Queue blocked:" in notices[-1]
    assert "missing capability heartbeat" in notices[-1]
    assert len(mq.list_new_envelopes()) == 1
    assert mq.list_inflight_envelopes() == []
    assert list((tmp_path / "bus" / "inbox").rglob("*.json")) == []


def test_drain_message_queue_capability_block_uses_short_retry_delay(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    monkeypatch.setattr("zeus.dashboard.app.time.time", lambda: 100.0)

    app = ZeusApp()
    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [target]
    app._message_receipts = {}

    env = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="wake-up",
    )
    mq.enqueue_envelope(env)

    app._drain_message_queue()

    queued = mq.list_new_envelopes()
    assert len(queued) == 1
    deferred = mq.load_envelope(queued[0])
    assert deferred is not None
    assert deferred.attempts == 1
    assert deferred.next_attempt_at == 102.0


def test_drain_message_queue_unpauses_paused_agent_targets_before_bus_handoff(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()

    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [target]
    app._message_receipts = {}
    app._agent_priorities = {"target": 4}
    _write_capability(tmp_path, "agent-target")

    env = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="wake-up",
    )
    mq.enqueue_envelope(env)

    app._drain_message_queue()

    inbox_files = sorted((tmp_path / "bus" / "inbox" / "agent-target" / "new").glob("*.json"))
    assert len(inbox_files) == 1
    assert app._agent_priorities.get("target", 3) == 3


def test_drain_message_queue_clears_dependency_for_blocked_target_from_blocker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()

    source = _agent("source", 1, agent_id="agent-source")
    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [source, target]
    app._message_receipts = {}
    app._agent_priorities = {"target": 4}
    target_dep_key = app._agent_dependency_key(target)
    app._agent_dependencies = {target_dep_key: app._agent_dependency_key(source)}
    _write_capability(tmp_path, "agent-target")

    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: True)

    env = mq.OutboundEnvelope.new(
        source_name="source",
        source_agent_id="agent-source",
        target_kind="agent",
        target_ref="agent-target",
        target_agent_id="agent-target",
        message="release",
    )
    mq.enqueue_envelope(env)

    app._drain_message_queue()

    inbox_files = sorted((tmp_path / "bus" / "inbox" / "agent-target" / "new").glob("*.json"))
    assert len(inbox_files) == 1
    assert target_dep_key not in app._agent_dependencies
    assert app._agent_priorities.get("target", 3) == 4


def test_drain_message_queue_dedupes_same_message_id_per_recipient(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _advance_clock(monkeypatch)

    app = ZeusApp()

    target = _agent("target", 2, agent_id="agent-target")
    app.agents = [target]
    app._message_receipts = {}
    _write_capability(tmp_path, "agent-target")

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
    _write_accepted_receipt(tmp_path, "agent-target", "msg-1")
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

    inbox_files = sorted((tmp_path / "bus" / "inbox" / "agent-target" / "new").glob("*.json"))
    assert len(inbox_files) == 1
    assert mq.list_new_envelopes() == []
    assert mq.list_inflight_envelopes() == []
