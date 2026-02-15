"""Tests for dashboard focus behavior."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.widgets import ZeusTextArea


class _DummyFocusable:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True


def test_dashboard_restores_table_focus_on_app_focus(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyFocusable()

    monkeypatch.setattr(app, "_has_modal_open", lambda: False)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: table)

    app.on_app_focus()

    assert table.focused is True


def test_dashboard_does_not_steal_focus_when_modal_is_open(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyFocusable()

    monkeypatch.setattr(app, "_has_modal_open", lambda: True)
    monkeypatch.setattr(app, "query_one", lambda selector, cls=None: table)

    app.on_app_focus()

    assert table.focused is False


def test_tab_toggle_focus_from_text_input_goes_to_table(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyFocusable()
    text_input = ZeusTextArea("")

    monkeypatch.setattr(ZeusApp, "focused", property(lambda self: text_input))
    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, cls=None: table if selector == "#agent-table" else text_input,
    )

    app.action_toggle_focus()

    assert table.focused is True


def test_tab_toggle_focus_from_stream_goes_to_text_input(monkeypatch) -> None:
    app = ZeusApp()
    table = _DummyFocusable()
    text_input = _DummyFocusable()
    stream = _DummyFocusable()

    monkeypatch.setattr(ZeusApp, "focused", property(lambda self: stream))

    def _query(selector: str, cls=None):
        if selector == "#agent-table":
            return table
        if selector == "#interact-input":
            return text_input
        return stream

    monkeypatch.setattr(app, "query_one", _query)

    app.action_toggle_focus()

    assert text_input.focused is True
    assert table.focused is False
