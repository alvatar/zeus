"""Tests for snapshot save/restore dashboard actions."""

from __future__ import annotations

from pathlib import Path

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import RestoreSnapshotScreen, SaveSnapshotScreen
from zeus.models import AgentWindow
from zeus.snapshots import RestoreSnapshotResult, SaveSnapshotResult


def _agent(name: str = "alpha") -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name=name,
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
        agent_id="agent-alpha",
    )


def test_action_save_snapshot_pushes_save_dialog(monkeypatch) -> None:
    app = ZeusApp()
    pushed: list[object] = []

    monkeypatch.setattr(app, "_has_blocking_modal_open", lambda: False)
    monkeypatch.setattr("zeus.dashboard.app.default_snapshot_name", lambda: "snap-a")
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_save_snapshot()

    assert pushed
    assert isinstance(pushed[0], SaveSnapshotScreen)


def test_action_restore_snapshot_notifies_when_none_available(monkeypatch) -> None:
    app = ZeusApp()
    notices: list[str] = []

    monkeypatch.setattr(app, "_has_blocking_modal_open", lambda: False)
    monkeypatch.setattr("zeus.dashboard.app.list_snapshot_files", lambda: [])
    monkeypatch.setattr(app, "notify_force", lambda msg, timeout=3: notices.append(msg))

    app.action_restore_snapshot()

    assert notices[-1] == "No snapshots found"


def test_action_restore_snapshot_pushes_restore_dialog(monkeypatch, tmp_path: Path) -> None:
    app = ZeusApp()
    pushed: list[object] = []

    snapshot = tmp_path / "snap-1.json"
    snapshot.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(app, "_has_blocking_modal_open", lambda: False)
    monkeypatch.setattr("zeus.dashboard.app.list_snapshot_files", lambda: [snapshot])
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_restore_snapshot()

    assert pushed
    assert isinstance(pushed[0], RestoreSnapshotScreen)


def test_do_save_snapshot_reports_failure(monkeypatch) -> None:
    app = ZeusApp()
    app.agents = [_agent()]

    notices: list[str] = []

    monkeypatch.setattr(
        "zeus.dashboard.app.save_snapshot_from_dashboard",
        lambda **_kwargs: SaveSnapshotResult(
            ok=False,
            errors=["missing restorable session path"],
        ),
    )
    monkeypatch.setattr(app, "notify_force", lambda msg, timeout=3: notices.append(msg))

    ok = app.do_save_snapshot("daily", close_all=False)

    assert ok is False
    assert notices[-1].startswith("Snapshot save failed:")


def test_do_restore_snapshot_reports_success(monkeypatch) -> None:
    app = ZeusApp()
    notices: list[str] = []
    timers: list[float] = []

    monkeypatch.setattr(
        "zeus.dashboard.app.restore_snapshot",
        lambda **_kwargs: RestoreSnapshotResult(
            ok=True,
            path="/tmp/snap.json",
            restored_count=3,
            skipped_count=1,
        ),
    )
    monkeypatch.setattr(app, "notify_force", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "set_timer", lambda delay, _cb: timers.append(delay))

    ok = app.do_restore_snapshot(
        "/tmp/snap.json",
        workspace_mode="original",
        if_running="error",
    )

    assert ok is True
    assert notices[-1] == "Restored snapshot: snap.json (3 restored, 1 skipped)"
    assert timers == [0.7]
