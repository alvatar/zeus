"""Tests for dashboard focus behavior."""

from zeus.dashboard.app import ZeusApp


class _DummyTable:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True


def test_dashboard_restores_table_focus_on_app_focus(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyTable()

    monkeypatch.setattr(app, "_has_modal_open", lambda: False)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: table)

    app.on_app_focus()

    assert table.focused is True


def test_dashboard_does_not_steal_focus_when_modal_is_open(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyTable()

    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: table)

    app.on_app_focus()

    assert table.focused is False
