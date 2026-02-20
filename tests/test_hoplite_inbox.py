from __future__ import annotations

import json

import zeus.hoplite_inbox as inbox


def test_enqueue_hoplite_inbox_message_writes_json_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(inbox, "HOPLITE_INBOX_DIR", tmp_path)

    ok = inbox.enqueue_hoplite_inbox_message(
        "hoplite-1",
        "hello",
        message_id="msg-1",
        source_name="polemarch",
        source_agent_id="agent-polemarch",
    )

    assert ok is True

    files = sorted((tmp_path / "hoplite-1").glob("*.json"))
    assert len(files) == 1

    payload = json.loads(files[0].read_text())
    assert payload["id"] == "msg-1"
    assert payload["message"] == "hello"
    assert payload["source_name"] == "polemarch"
    assert payload["source_agent_id"] == "agent-polemarch"


def test_enqueue_hoplite_inbox_message_rejects_empty_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(inbox, "HOPLITE_INBOX_DIR", tmp_path)

    assert inbox.enqueue_hoplite_inbox_message("", "hello") is False
    assert inbox.enqueue_hoplite_inbox_message("hoplite-1", "   ") is False
    assert list(tmp_path.rglob("*.json")) == []


def test_enqueue_hoplite_inbox_message_sanitizes_agent_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(inbox, "HOPLITE_INBOX_DIR", tmp_path)

    ok = inbox.enqueue_hoplite_inbox_message("../hoplite-1", "payload")

    assert ok is True
    assert (tmp_path / "hoplite-1").is_dir()
