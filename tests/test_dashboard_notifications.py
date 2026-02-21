"""Tests for dashboard notification gating."""

from textual.app import App

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import NoticeScreen


def test_notify_is_disabled_by_default(monkeypatch) -> None:
    app = ZeusApp()
    app._notifications_enabled = False

    called: list[str] = []

    def fake_notify(self, message, **kwargs):  # type: ignore[no-untyped-def]
        called.append(message)

    monkeypatch.setattr(App, "notify", fake_notify)

    app.notify("hidden")

    assert called == []


def test_notify_forwards_when_enabled(monkeypatch) -> None:
    app = ZeusApp()
    app._notifications_enabled = True

    called: list[str] = []

    def fake_notify(self, message, **kwargs):  # type: ignore[no-untyped-def]
        called.append(message)

    monkeypatch.setattr(App, "notify", fake_notify)

    app.notify("shown")

    assert called == ["shown"]


def test_notify_force_bypasses_disabled_gate(monkeypatch) -> None:
    app = ZeusApp()
    app._notifications_enabled = False

    called: list[str] = []

    def fake_notify(self, message, **kwargs):  # type: ignore[no-untyped-def]
        called.append(message)

    monkeypatch.setattr(App, "notify", fake_notify)

    app.notify_force("forced")

    assert called == ["forced"]


def test_notify_warning_uses_notice_modal_when_running(monkeypatch) -> None:
    app = ZeusApp()
    app._notifications_enabled = True

    pushed: list[object] = []
    called: list[str] = []

    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: True))
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(
        App,
        "notify",
        lambda self, message, **kwargs: called.append(message),  # type: ignore[no-untyped-def]
    )

    app.notify("warn", severity="warning")

    assert called == []
    assert len(pushed) == 1
    assert isinstance(pushed[0], NoticeScreen)


def test_notify_force_uses_notice_modal_when_running(monkeypatch) -> None:
    app = ZeusApp()

    pushed: list[object] = []
    called: list[str] = []

    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: True))
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(
        App,
        "notify",
        lambda self, message, **kwargs: called.append(message),  # type: ignore[no-untyped-def]
    )

    app.notify_force("forced")

    assert called == []
    assert len(pushed) == 1
    assert isinstance(pushed[0], NoticeScreen)
