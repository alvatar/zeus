"""Tests for celebration overlay dismissal behavior."""

from zeus.dashboard.widgets import DopamineOverlay, SteadyLadOverlay


def test_dopamine_overlay_focuses_on_mount(monkeypatch) -> None:
    overlay = DopamineOverlay(80.0)

    focused: list[bool] = []
    monkeypatch.setattr(overlay, "focus", lambda: focused.append(True))
    monkeypatch.setattr(overlay, "set_interval", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay, "set_timer", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay, "_spawn_firework", lambda: None)

    overlay.on_mount()

    assert focused == [True]


def test_steady_lad_overlay_focuses_on_mount(monkeypatch) -> None:
    overlay = SteadyLadOverlay(60.0)

    focused: list[bool] = []
    monkeypatch.setattr(overlay, "focus", lambda: focused.append(True))
    monkeypatch.setattr(overlay, "set_interval", lambda *args, **kwargs: None)
    monkeypatch.setattr(overlay, "set_timer", lambda *args, **kwargs: None)

    overlay.on_mount()

    assert focused == [True]
