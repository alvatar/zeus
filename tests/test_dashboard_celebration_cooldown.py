"""Tests for celebration cooldown gating."""

from zeus.dashboard.app import ZeusApp


def test_celebration_ready_requires_full_hour() -> None:
    app = ZeusApp()
    app._celebration_cooldown_started_at = 100.0

    assert app._celebration_ready(now=3699.9) is False
    assert app._celebration_ready(now=3700.0) is True


def test_maybe_trigger_celebration_blocked_by_cooldown(monkeypatch) -> None:
    app = ZeusApp()
    calls: list[str] = []

    monkeypatch.setattr(app, "_celebration_ready", lambda: False)
    monkeypatch.setattr(app, "_show_steady_lad", lambda eff: calls.append("steady") or True)
    monkeypatch.setattr(app, "_show_dopamine_hit", lambda eff: calls.append("dopamine") or True)

    app._steady_armed = True
    app._dopamine_armed = True
    app._maybe_trigger_celebration(85.0)

    assert calls == []


def test_maybe_trigger_celebration_prefers_steady_when_ready(monkeypatch) -> None:
    app = ZeusApp()
    calls: list[str] = []

    monkeypatch.setattr(app, "_celebration_ready", lambda: True)
    monkeypatch.setattr(app, "_show_steady_lad", lambda eff: calls.append("steady") or True)
    monkeypatch.setattr(app, "_show_dopamine_hit", lambda eff: calls.append("dopamine") or True)

    app._steady_armed = True
    app._dopamine_armed = True
    app._maybe_trigger_celebration(85.0)

    assert calls == ["steady"]
    assert app._steady_armed is False


def test_maybe_trigger_celebration_rearms_when_efficiency_drops(monkeypatch) -> None:
    app = ZeusApp()
    monkeypatch.setattr(app, "_celebration_ready", lambda: False)

    app._steady_armed = False
    app._dopamine_armed = False

    app._maybe_trigger_celebration(50.0)

    assert app._steady_armed is True
    assert app._dopamine_armed is True
