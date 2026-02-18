"""Tests for runtime session map resolution."""

from __future__ import annotations

import json
from pathlib import Path

import zeus.session_runtime as session_runtime


def test_read_runtime_session_path_returns_none_for_missing_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_reads_valid_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    payload = {
        "agentId": "agent-1",
        "sessionPath": "/tmp/session.jsonl",
        "updatedAt": "2026-02-18T00:00:00.000Z",
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") == "/tmp/session.jsonl"


def test_read_runtime_session_path_rejects_mismatched_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    payload = {
        "agentId": "other-agent",
        "sessionPath": "/tmp/session.jsonl",
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_non_absolute_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    payload = {
        "agentId": "agent-1",
        "sessionPath": "relative/session.jsonl",
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_invalid_agent_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    assert session_runtime.read_runtime_session_path("../agent") is None
