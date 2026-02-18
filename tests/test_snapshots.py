"""Tests for snapshot save/restore helpers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from zeus import snapshots
from zeus.models import AgentWindow, State, TmuxSession


def _agent(
    name: str,
    *,
    cwd: str = "/tmp/project",
    agent_id: str = "agent-1",
    backend: str = "kitty",
    tmux_session: str = "",
) -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name=name,
        pid=101,
        kitty_pid=201,
        cwd=cwd,
        agent_id=agent_id,
        backend=backend,
        tmux_session=tmux_session,
    )


def test_save_snapshot_rejects_ambiguous_cwd_fallback(monkeypatch, tmp_path: Path) -> None:
    snap_dir = tmp_path / "snapshots"
    session_file = tmp_path / "session.jsonl"
    session_file.write_text('{"type":"session"}\n', encoding="utf-8")

    a1 = _agent("a1", cwd="/tmp/shared", agent_id="agent-a")
    a2 = _agent("a2", cwd="/tmp/shared", agent_id="agent-b")

    monkeypatch.setattr(snapshots, "SNAPSHOTS_DIR", snap_dir)
    monkeypatch.setattr(
        snapshots,
        "resolve_agent_session_path_with_source",
        lambda _agent: (str(session_file), "cwd"),
    )

    result = snapshots.save_snapshot_from_dashboard(
        name="ambiguous",
        agents=[a1, a2],
        close_all=False,
    )

    assert result.ok is False
    assert result.errors
    assert "ambiguous cwd fallback" in result.errors[0]


def test_save_snapshot_writes_entries_and_working_ids(monkeypatch, tmp_path: Path) -> None:
    snap_dir = tmp_path / "snapshots"
    session_file = tmp_path / "session.jsonl"
    session_file.write_text('{"type":"session"}\n', encoding="utf-8")

    agent = _agent("alpha", agent_id="agent-alpha")
    agent.state = State.WORKING
    agent.workspace = "DP-1:3"

    monkeypatch.setattr(snapshots, "SNAPSHOTS_DIR", snap_dir)
    monkeypatch.setattr(
        snapshots,
        "resolve_agent_session_path_with_source",
        lambda _agent: (str(session_file), "env"),
    )

    result = snapshots.save_snapshot_from_dashboard(
        name="daily",
        agents=[agent],
        close_all=False,
    )

    assert result.ok is True
    assert result.path

    payload = json.loads(Path(result.path).read_text(encoding="utf-8"))
    assert payload["schema_version"] == snapshots.SNAPSHOT_SCHEMA_VERSION
    assert payload["working_agent_ids"] == ["agent-alpha"]
    assert payload["entry_count"] == 1
    assert payload["entries"][0]["kind"] == "kitty"
    assert payload["entries"][0]["session_path"] == str(session_file)


def test_restore_snapshot_errors_when_agent_id_already_running(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_file = tmp_path / "session.jsonl"
    session_file.write_text('{"type":"session"}\n', encoding="utf-8")

    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps(
            {
                "schema_version": snapshots.SNAPSHOT_SCHEMA_VERSION,
                "entries": [
                    {
                        "kind": "kitty",
                        "name": "alpha",
                        "agent_id": "agent-alpha",
                        "role": "hippeus",
                        "cwd": "/tmp/project",
                        "workspace": "DP-1:3",
                        "session_path": str(session_file),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(snapshots, "discover_agents", lambda: [_agent("live", agent_id="agent-alpha")])
    monkeypatch.setattr(snapshots, "discover_tmux_sessions", lambda: [])

    launched: list[bool] = []

    def _fake_popen(*_args, **_kwargs):  # noqa: ANN002, ANN003
        launched.append(True)
        raise AssertionError("must not launch on conflict")

    monkeypatch.setattr(snapshots.subprocess, "Popen", _fake_popen)

    result = snapshots.restore_snapshot(
        snapshot_path=str(snapshot_file),
        workspace_mode="original",
        if_running="error",
    )

    assert result.ok is False
    assert "already running" in result.errors[0]
    assert launched == []


def test_restore_snapshot_kitty_current_workspace_skips_move(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_file = tmp_path / "session.jsonl"
    session_file.write_text('{"type":"session"}\n', encoding="utf-8")

    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(
        json.dumps(
            {
                "schema_version": snapshots.SNAPSHOT_SCHEMA_VERSION,
                "entries": [
                    {
                        "kind": "kitty",
                        "name": "alpha",
                        "agent_id": "agent-alpha",
                        "role": "hippeus",
                        "cwd": "/tmp/project",
                        "workspace": "DP-1:3",
                        "session_path": str(session_file),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(snapshots, "discover_agents", lambda: [])
    monkeypatch.setattr(snapshots, "discover_tmux_sessions", lambda: [])

    class _DummyProc:
        pid = 777

    popen_calls: list[list[str]] = []

    def _fake_popen(cmd, **_kwargs):  # noqa: ANN001
        popen_calls.append(list(cmd))
        return _DummyProc()

    moved: list[tuple[int, str]] = []

    monkeypatch.setattr(snapshots.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(
        snapshots,
        "move_pid_to_workspace_and_focus_later",
        lambda pid, workspace, delay=0.5: moved.append((pid, workspace)),
    )

    result = snapshots.restore_snapshot(
        snapshot_path=str(snapshot_file),
        workspace_mode="current",
        if_running="error",
    )

    assert result.ok is True
    assert result.restored_count == 1
    assert moved == []
    assert popen_calls


def test_restore_snapshot_hoplite_sets_tmux_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    session_file = tmp_path / "session.jsonl"
    session_file.write_text('{"type":"session"}\n', encoding="utf-8")

    snapshot_file = tmp_path / "snapshot-hoplite.json"
    snapshot_file.write_text(
        json.dumps(
            {
                "schema_version": snapshots.SNAPSHOT_SCHEMA_VERSION,
                "entries": [
                    {
                        "kind": "hoplite",
                        "name": "hoplite-a",
                        "agent_id": "hoplite-1",
                        "role": "hoplite",
                        "cwd": "/tmp/project",
                        "tmux_session": "hoplite-1",
                        "session_path": str(session_file),
                        "owner_id": "polemarch-1",
                        "phalanx_id": "phalanx-polemarch-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(snapshots, "discover_agents", lambda: [])
    monkeypatch.setattr(snapshots, "discover_tmux_sessions", lambda: [])

    tmux_calls: list[list[str]] = []

    def _fake_run_tmux(command: list[str], *, timeout: float):
        tmux_calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(snapshots, "_run_tmux", _fake_run_tmux)

    result = snapshots.restore_snapshot(
        snapshot_path=str(snapshot_file),
        workspace_mode="original",
        if_running="error",
    )

    assert result.ok is True
    assert result.restored_count == 1
    assert any(call[:3] == ["tmux", "new-session", "-d"] for call in tmux_calls)
    assert any(
        call[:5] == ["tmux", "set-option", "-t", "hoplite-1", "@zeus_owner"]
        and call[5] == "polemarch-1"
        for call in tmux_calls
    )
    assert any(
        call[:5] == ["tmux", "set-option", "-t", "hoplite-1", "@zeus_phalanx"]
        and call[5] == "phalanx-polemarch-1"
        for call in tmux_calls
    )
