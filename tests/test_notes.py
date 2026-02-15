"""Tests for per-agent notes persistence."""

import zeus.notes as notes


def test_load_agent_notes_returns_empty_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "AGENT_NOTES_FILE", tmp_path / "missing.json")
    assert notes.load_agent_notes() == {}


def test_save_and_load_agent_notes_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    monkeypatch.setattr(notes, "AGENT_NOTES_FILE", path)

    notes.save_agent_notes({
        "a": "hello",
        "b": "  ",  # filtered out
    })

    assert notes.load_agent_notes() == {"a": "hello"}
