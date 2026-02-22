"""Tests for snapshot save/restore dashboard actions."""

from __future__ import annotations

from asyncio import InvalidStateError
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


def test_save_snapshot_screen_action_dismiss_ignores_invalid_state(monkeypatch) -> None:
    screen = SaveSnapshotScreen(default_name="snap-a")

    monkeypatch.setattr(
        screen,
        "dismiss",
        lambda: (_ for _ in ()).throw(InvalidStateError("invalid state")),
    )

    # Should not raise.
    screen.action_dismiss()


def test_save_snapshot_screen_confirm_starts_async_save_and_enters_saving_state(monkeypatch) -> None:
    screen = SaveSnapshotScreen(default_name="snap-a")

    start_calls: list[tuple[str, bool]] = []

    class _ZeusStub:
        def notify_force(self, _message: str, timeout: int = 3) -> None:  # noqa: ARG002
            return

        def do_start_snapshot_save(self, name: str, *, close_all: bool) -> int | None:
            start_calls.append((name, close_all))
            return 7

    monkeypatch.setattr(SaveSnapshotScreen, "zeus", property(lambda self: _ZeusStub()))
    monkeypatch.setattr(screen, "_name_value", lambda: "snap-a")
    monkeypatch.setattr(screen, "_close_all_value", lambda: False)

    entered: list[str] = []
    monkeypatch.setattr(screen, "_enter_saving_state", lambda name: entered.append(name))

    screen.action_confirm()

    assert start_calls == [("snap-a", False)]
    assert entered == ["snap-a"]
    assert screen.save_job_id == 7


def test_save_snapshot_screen_dismiss_while_saving_notifies_and_does_not_dismiss(
    monkeypatch,
) -> None:
    screen = SaveSnapshotScreen(default_name="snap-a")
    screen._saving = True

    notices: list[str] = []

    class _ZeusStub:
        def notify(self, message: str, timeout: int = 3) -> None:
            notices.append(message)

    monkeypatch.setattr(SaveSnapshotScreen, "zeus", property(lambda self: _ZeusStub()))
    monkeypatch.setattr(
        screen,
        "dismiss",
        lambda: (_ for _ in ()).throw(AssertionError("must not dismiss while saving")),
    )

    screen.action_dismiss()

    assert notices == ["Snapshot save in progress…"]


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


def test_do_start_snapshot_save_schedules_async_task(monkeypatch) -> None:
    import asyncio

    app = ZeusApp()
    app.agents = [_agent()]

    futures: list[object] = []
    monkeypatch.setattr(
        asyncio,
        "ensure_future",
        lambda coro: (futures.append(coro), coro.close()),  # capture without running
    )

    job_id = app.do_start_snapshot_save("daily", close_all=True)

    assert job_id == 1
    assert app._snapshot_save_active_job == 1
    assert len(futures) == 1


def test_do_start_snapshot_save_rejects_when_active(monkeypatch) -> None:
    app = ZeusApp()
    app._snapshot_save_active_job = 3

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))

    job_id = app.do_start_snapshot_save("daily", close_all=False)

    assert job_id is None
    assert notices == ["Snapshot save already in progress"]


def test_finish_snapshot_save_job_clears_active_and_reports(monkeypatch) -> None:
    app = ZeusApp()
    app._snapshot_save_active_job = 9

    dismiss_calls: list[int] = []
    handle_calls: list[bool] = []

    monkeypatch.setattr(
        app,
        "_dismiss_snapshot_save_screen",
        lambda job_id: dismiss_calls.append(job_id),
    )
    monkeypatch.setattr(
        app,
        "_handle_snapshot_save_result",
        lambda result, *, close_all: handle_calls.append(close_all) or True,
    )

    result = SaveSnapshotResult(ok=True, path="/tmp/daily.json", entry_count=1)
    app._finish_snapshot_save_job(9, True, result)

    assert app._snapshot_save_active_job is None
    assert dismiss_calls == [9]
    assert handle_calls == [True]


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


def test_do_restore_snapshot_reports_working_state_recovery(monkeypatch) -> None:
    app = ZeusApp()
    notices: list[str] = []

    monkeypatch.setattr(
        "zeus.dashboard.app.restore_snapshot",
        lambda **_kwargs: RestoreSnapshotResult(
            ok=True,
            path="/tmp/snap.json",
            restored_count=2,
            skipped_count=0,
            working_total=3,
            working_restored=2,
            working_skipped=1,
        ),
    )
    monkeypatch.setattr(app, "notify_force", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "set_timer", lambda _delay, _cb: None)

    ok = app.do_restore_snapshot(
        "/tmp/snap.json",
        workspace_mode="original",
        if_running="error",
    )

    assert ok is True
    assert (
        notices[-1]
        == "Restored snapshot: snap.json (2 restored); previously WORKING: 2/3 restored, 1 skipped"
    )


# ── RestoreSnapshotScreen dismiss race ──────────────────────────────

def test_restore_snapshot_screen_dismiss_safe_tolerates_invalid_state(
    tmp_path: Path,
) -> None:
    from asyncio import InvalidStateError

    snap = tmp_path / "snap.json"
    snap.write_text("{}", encoding="utf-8")
    screen = RestoreSnapshotScreen(snapshot_files=[snap])

    calls: list[bool] = []

    def _bad_dismiss(*_a: object, **_k: object) -> None:
        calls.append(True)
        raise InvalidStateError("already set")

    # Bypass the override so _dismiss_safe calls the broken base dismiss
    object.__setattr__(screen, "dismiss", _bad_dismiss)

    # Should not raise
    screen._dismiss_safe()
    assert calls == [True]


def test_restore_snapshot_screen_action_dismiss_uses_safe_dismiss(
    tmp_path: Path,
) -> None:
    snap = tmp_path / "snap.json"
    snap.write_text("{}", encoding="utf-8")
    screen = RestoreSnapshotScreen(snapshot_files=[snap])

    safe_calls: list[bool] = []
    screen._dismiss_safe = lambda: safe_calls.append(True)

    screen.action_dismiss()
    assert safe_calls == [True]


# ── Worker crash recovery ───────────────────────────────────────────

def test_run_snapshot_save_catches_exception_and_finishes(monkeypatch) -> None:
    """If save_snapshot_from_dashboard raises, the async task must still call
    _finish_snapshot_save_job so the dialog isn't stuck forever."""
    import asyncio

    app = ZeusApp()
    app._snapshot_save_active_job = 7

    finish_calls: list[tuple[int, bool, SaveSnapshotResult]] = []
    monkeypatch.setattr(
        app,
        "_finish_snapshot_save_job",
        lambda job_id, close_all, result: finish_calls.append(
            (job_id, close_all, result)
        ),
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.save_snapshot_from_dashboard",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("disk exploded")),
    )

    asyncio.run(app._run_snapshot_save(7, "boom", False, [_agent()]))

    assert len(finish_calls) == 1
    job_id, close_all, result = finish_calls[0]
    assert job_id == 7
    assert close_all is False
    assert result.ok is False
    assert "disk exploded" in result.errors[0]
