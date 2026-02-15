"""Tests for dashboard notification gating."""

from textual.app import App

from zeus.dashboard.app import ZeusApp


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
