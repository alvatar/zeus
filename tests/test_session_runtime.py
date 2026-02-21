"""Tests for runtime session map resolution."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import zeus.session_runtime as session_runtime


def _iso_utc(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def test_read_runtime_session_path_returns_none_for_missing_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_reads_valid_payload(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}")

    payload = {
        "agentId": "agent-1",
        "sessionPath": str(session_file),
        "updatedAt": _iso_utc(190.0),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") == str(session_file)


def test_read_runtime_session_path_rejects_mismatched_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}")

    payload = {
        "agentId": "other-agent",
        "sessionPath": str(session_file),
        "updatedAt": _iso_utc(190.0),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_non_absolute_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    payload = {
        "agentId": "agent-1",
        "sessionPath": "relative/session.jsonl",
        "updatedAt": _iso_utc(190.0),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_invalid_agent_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))

    assert session_runtime.read_runtime_session_path("../agent") is None


def test_read_runtime_session_path_rejects_missing_session_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    payload = {
        "agentId": "agent-1",
        "sessionPath": str(tmp_path / "missing.jsonl"),
        "updatedAt": _iso_utc(190.0),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_stale_runtime_map(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setenv("ZEUS_SESSION_MAP_MAX_AGE_S", "5")
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}")

    payload = {
        "agentId": "agent-1",
        "sessionPath": str(session_file),
        "updatedAt": _iso_utc(190.0),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None


def test_read_runtime_session_path_rejects_missing_updated_at(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ZEUS_SESSION_MAP_DIR", str(tmp_path))
    monkeypatch.setattr(session_runtime.time, "time", lambda: 200.0)

    session_file = tmp_path / "session.jsonl"
    session_file.write_text("{}")

    payload = {
        "agentId": "agent-1",
        "sessionPath": str(session_file),
    }
    (tmp_path / "agent-1.json").write_text(json.dumps(payload))

    assert session_runtime.read_runtime_session_path("agent-1") is None
