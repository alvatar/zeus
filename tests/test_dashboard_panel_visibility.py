"""Tests for dashboard panel visibility persistence."""

import json

import zeus.dashboard.app as app_mod
from zeus.dashboard.app import ZeusApp


class _DummyWidget:
    def __init__(self) -> None:
        self.classes: set[str] = set()

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)


class _DummyTable:
    def __init__(self) -> None:
        self.focused = False

    def focus(self) -> None:
        self.focused = True


def test_save_panel_visibility_omits_legacy_table_key(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "panels.json"
    monkeypatch.setattr(app_mod, "PANEL_VISIBILITY_FILE", path)

    app = ZeusApp()
    app._show_interact_input = False
    app._show_minimap = False
    app._show_sparklines = True
    app._show_target_band = False

    app._save_panel_visibility()

    data = json.loads(path.read_text())
    assert data == {
        "interact_input": False,
        "minimap": False,
        "sparklines": True,
        "target_band": False,
    }
    assert "table" not in data


def test_toggle_interact_input_updates_visibility_and_persists(monkeypatch) -> None:
    app = ZeusApp()
    app._show_interact_input = True

    applied: list[bool] = []
    saved: list[bool] = []

    monkeypatch.setattr(app, "_apply_panel_visibility", lambda: applied.append(True))
    monkeypatch.setattr(app, "_save_panel_visibility", lambda: saved.append(True))

    app.action_toggle_interact_input()

    assert app._show_interact_input is False
    assert applied == [True]
    assert saved == [True]


def test_load_panel_visibility_migrates_legacy_table_key_away(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "panels.json"
    path.write_text(
        json.dumps(
            {
                "table": False,
                "interact_input": False,
                "minimap": False,
                "sparklines": True,
                "target_band": False,
            }
        )
    )
    monkeypatch.setattr(app_mod, "PANEL_VISIBILITY_FILE", path)

    app = ZeusApp()
    app._load_panel_visibility()

    assert app._show_interact_input is False
    assert app._show_minimap is False
    assert app._show_sparklines is True
    assert app._show_target_band is False

    data = json.loads(path.read_text())
    assert data == {
        "interact_input": False,
        "minimap": False,
        "sparklines": True,
        "target_band": False,
    }
    assert "table" not in data


def test_target_band_is_hidden_when_interact_input_is_hidden(monkeypatch) -> None:
    app = ZeusApp()
    app._show_interact_input = False
    app._show_target_band = True
    app._show_minimap = True
    app._show_sparklines = True

    mini = _DummyWidget()
    spark = _DummyWidget()
    target = _DummyWidget()
    interact_input = _DummyWidget()
    table = _DummyTable()

    def _query_one(selector: str, cls=None):
        lookup = {
            "#mini-map": mini,
            "#sparkline-chart": spark,
            "#interact-target": target,
            "#interact-input": interact_input,
            "#agent-table": table,
        }
        return lookup[selector]

    monkeypatch.setattr(app, "query_one", _query_one)
    monkeypatch.setattr(ZeusApp, "focused", property(lambda self: None))

    app._apply_panel_visibility()

    assert "hidden" in interact_input.classes
    assert "hidden" in target.classes

    app._show_interact_input = True
    app._apply_panel_visibility()

    assert "hidden" not in interact_input.classes
    assert "hidden" not in target.classes
