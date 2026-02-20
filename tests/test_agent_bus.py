from __future__ import annotations

import json
import time

import zeus.agent_bus as bus


def _configure_dirs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(bus, "AGENT_BUS_INBOX_DIR", tmp_path / "inbox")
    monkeypatch.setattr(bus, "AGENT_BUS_RECEIPTS_DIR", tmp_path / "receipts")
    monkeypatch.setattr(bus, "AGENT_BUS_CAPS_DIR", tmp_path / "caps")
    monkeypatch.setattr(bus, "AGENT_BUS_PROCESSED_DIR", tmp_path / "processed")


def test_enqueue_agent_bus_message_writes_inbox_new_file(monkeypatch, tmp_path) -> None:
    _configure_dirs(monkeypatch, tmp_path)

    ok = bus.enqueue_agent_bus_message(
        "agent-1",
        "hello",
        message_id="msg-1",
        source_name="sender",
        source_agent_id="sender-id",
        source_role="polemarch",
    )

    assert ok is True
    files = sorted((tmp_path / "inbox" / "agent-1" / "new").glob("*.json"))
    assert len(files) == 1

    payload = json.loads(files[0].read_text())
    assert payload["id"] == "msg-1"
    assert payload["message"] == "hello"
    assert payload["source_name"] == "sender"
    assert payload["source_agent_id"] == "sender-id"
    assert payload["source_role"] == "polemarch"
    assert payload["deliver_as"] == "followUp"


def test_has_agent_bus_receipt_requires_matching_id(monkeypatch, tmp_path) -> None:
    _configure_dirs(monkeypatch, tmp_path)

    receipt_dir = tmp_path / "receipts" / "agent-1"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "msg-1.json").write_text(
        json.dumps({"id": "msg-1", "status": "accepted", "accepted_at": time.time()})
    )

    assert bus.has_agent_bus_receipt("agent-1", "msg-1") is True
    assert bus.has_agent_bus_receipt("agent-1", "msg-2") is False


def test_capability_health_checks_stale_and_fresh(monkeypatch, tmp_path) -> None:
    _configure_dirs(monkeypatch, tmp_path)

    ok, reason = bus.capability_health("agent-1", max_age_s=10.0, now=100.0)
    assert ok is False
    assert "missing capability heartbeat" in (reason or "")

    caps_dir = tmp_path / "caps"
    caps_dir.mkdir(parents=True, exist_ok=True)

    (caps_dir / "agent-1.json").write_text(
        json.dumps({"updated_at": 50.0, "supports": {"queue_bus": True}})
    )
    ok, reason = bus.capability_health("agent-1", max_age_s=10.0, now=100.0)
    assert ok is False
    assert "stale capability heartbeat" in (reason or "")

    (caps_dir / "agent-1.json").write_text(
        json.dumps({"updated_at": 98.0, "supports": {"queue_bus": True}})
    )
    ok, reason = bus.capability_health("agent-1", max_age_s=10.0, now=100.0)
    assert ok is True
    assert reason is None
