"""Tests for message preset loading from TOML."""

from __future__ import annotations

from pathlib import Path

from zeus.message_presets import (
    _DEFAULT_PREMADE,
    _DEFAULT_QUICK,
    load_premade_templates,
    load_quick_presets,
)


def test_load_quick_presets_returns_defaults_when_no_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", tmp_path / "missing.toml")
    result = load_quick_presets()
    assert result == _DEFAULT_QUICK
    assert len(result) == 4


def test_load_quick_presets_parses_all_four_slots(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[quick.1]\nname = "A"\ntext = "alpha"\n'
        '[quick.2]\nname = "B"\ntext = "beta"\n'
        '[quick.3]\nname = "C"\ntext = "gamma"\n'
        '[quick.4]\nname = "D"\ntext = "delta"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert result == [("A", "alpha"), ("B", "beta"), ("C", "gamma"), ("D", "delta")]


def test_load_quick_presets_fills_missing_slots_with_defaults(
    monkeypatch, tmp_path: Path,
) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[quick.1]\nname = "A"\ntext = "alpha"\n'
        '[quick.3]\nname = "C"\ntext = "gamma"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert result[0] == ("A", "alpha")
    assert result[1] == _DEFAULT_QUICK[1]
    assert result[2] == ("C", "gamma")
    assert result[3] == _DEFAULT_QUICK[3]


def test_load_quick_presets_returns_defaults_on_malformed_toml(
    monkeypatch, tmp_path: Path,
) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text("not valid toml {{{{", encoding="utf-8")
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert result == _DEFAULT_QUICK


def test_load_quick_presets_skips_entry_with_empty_name(
    monkeypatch, tmp_path: Path,
) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[quick.1]\nname = ""\ntext = "alpha"\n'
        '[quick.2]\nname = "B"\ntext = "beta"\n'
        '[quick.3]\nname = "C"\ntext = "gamma"\n'
        '[quick.4]\nname = "D"\ntext = "delta"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert result[0] == _DEFAULT_QUICK[0]  # fallback for empty name
    assert result[1] == ("B", "beta")


def test_load_premade_returns_defaults_when_no_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", tmp_path / "missing.toml")
    result = load_premade_templates()
    assert result == _DEFAULT_PREMADE


def test_load_premade_parses_entries(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[[premade]]\nname = "Go"\ntext = "go now"\n'
        '[[premade]]\nname = "Stop"\ntext = "halt"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_premade_templates()
    assert result == [("Go", "go now"), ("Stop", "halt")]


def test_load_premade_returns_defaults_when_empty_list(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text("premade = []\n", encoding="utf-8")
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_premade_templates()
    assert result == _DEFAULT_PREMADE


def test_load_premade_skips_entries_without_name(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[[premade]]\nname = ""\ntext = "nope"\n'
        '[[premade]]\nname = "Valid"\ntext = "yes"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_premade_templates()
    assert result == [("Valid", "yes")]


def test_quick_preset_text_preserves_whitespace(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[quick.1]\nname = "A"\ntext = "  leading and trailing  "\n'
        '[quick.2]\nname = "B"\ntext = "B"\n'
        '[quick.3]\nname = "C"\ntext = "C"\n'
        '[quick.4]\nname = "D"\ntext = "\\ntrailing newline\\n"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert result[0][1] == "  leading and trailing  "
    assert result[3][1] == "\ntrailing newline\n"


def test_premade_text_preserves_whitespace(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text(
        '[[premade]]\nname = "Go"\ntext = "  spaced  "\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_premade_templates()
    assert result[0][1] == "  spaced  "


def test_quick_presets_always_returns_four_entries(monkeypatch, tmp_path: Path) -> None:
    toml_file = tmp_path / "presets.toml"
    toml_file.write_text("[quick]\n", encoding="utf-8")
    monkeypatch.setattr("zeus.message_presets.PRESETS_FILE", toml_file)

    result = load_quick_presets()
    assert len(result) == 4
