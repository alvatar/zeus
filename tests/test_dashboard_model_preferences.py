"""Tests for invoke-dialog model preference persistence."""

import json

import zeus.dashboard.app as app_mod
from zeus.dashboard.app import ZeusApp


def test_load_model_preferences_reads_last_model(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    path.write_text(json.dumps({"last_model_spec": "openai/gpt-4o"}))
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)

    app = ZeusApp()
    app._load_model_preferences()

    assert app.do_get_last_invoke_model_spec() == "openai/gpt-4o"


def test_load_model_preferences_ignores_invalid_last_model(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    path.write_text(json.dumps({"last_model_spec": 123}))
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)

    app = ZeusApp()
    app._last_invoke_model_spec = "anthropic/claude-sonnet-4-5"
    app._load_model_preferences()

    assert app.do_get_last_invoke_model_spec() == "anthropic/claude-sonnet-4-5"


def test_set_last_invoke_model_spec_persists_when_running(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda self: True))

    app = ZeusApp()
    app.do_set_last_invoke_model_spec(" openai/gpt-4o ")

    data = json.loads(path.read_text())
    assert data["last_model_spec"] == "openai/gpt-4o"


def test_set_last_invoke_model_spec_skips_disk_when_not_running(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda self: False))

    app = ZeusApp()
    app.do_set_last_invoke_model_spec("openai/gpt-4o")

    assert not path.exists()
    assert app.do_get_last_invoke_model_spec() == "openai/gpt-4o"


def test_load_model_preferences_reads_review_theme_mode(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    path.write_text(json.dumps({"worktree_review_theme_mode": "light"}))
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)

    app = ZeusApp()
    app._load_model_preferences()

    assert app.do_get_worktree_review_theme_mode() == "light"


def test_load_model_preferences_invalid_review_theme_defaults_to_dark(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    path.write_text(json.dumps({"worktree_review_theme_mode": "nope"}))
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)

    app = ZeusApp()
    app._worktree_review_theme_mode = "light"
    app._load_model_preferences()

    assert app.do_get_worktree_review_theme_mode() == "dark"


def test_set_review_theme_mode_persists_when_running(tmp_path, monkeypatch) -> None:
    path = tmp_path / "invoke.json"
    monkeypatch.setattr(app_mod, "INVOKE_PREFERENCES_FILE", path)
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda self: True))

    app = ZeusApp()
    mode = app.do_set_worktree_review_theme_mode("light")

    data = json.loads(path.read_text())
    assert mode == "light"
    assert data["worktree_review_theme_mode"] == "light"


def test_toggle_review_theme_mode_flips_between_dark_and_light() -> None:
    app = ZeusApp()

    assert app.do_get_worktree_review_theme_mode() == "dark"
    assert app.do_toggle_worktree_review_theme_mode() == "light"
    assert app.do_toggle_worktree_review_theme_mode() == "dark"
