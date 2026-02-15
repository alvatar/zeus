"""Tests for dashboard panel visibility persistence."""

import json

import zeus.dashboard.app as app_mod
from zeus.dashboard.app import ZeusApp


def test_save_panel_visibility_omits_legacy_table_key(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "panels.json"
    monkeypatch.setattr(app_mod, "PANEL_VISIBILITY_FILE", path)

    app = ZeusApp()
    app._show_minimap = False
    app._show_sparklines = True
    app._show_target_band = False

    app._save_panel_visibility()

    data = json.loads(path.read_text())
    assert data == {
        "minimap": False,
        "sparklines": True,
        "target_band": False,
    }
    assert "table" not in data


def test_load_panel_visibility_migrates_legacy_table_key_away(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "panels.json"
    path.write_text(
        json.dumps(
            {
                "table": False,
                "minimap": False,
                "sparklines": True,
                "target_band": False,
            }
        )
    )
    monkeypatch.setattr(app_mod, "PANEL_VISIBILITY_FILE", path)

    app = ZeusApp()
    app._load_panel_visibility()

    assert app._show_minimap is False
    assert app._show_sparklines is True
    assert app._show_target_band is False

    data = json.loads(path.read_text())
    assert data == {
        "minimap": False,
        "sparklines": True,
        "target_band": False,
    }
    assert "table" not in data
