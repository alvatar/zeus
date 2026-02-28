"""Tests for dashboard help bindings content."""

import inspect

from zeus.dashboard.screens import HelpScreen, _HELP_BINDINGS


def test_help_places_agent_management_section_first() -> None:
    headers = [desc for key, desc in _HELP_BINDINGS if not key]
    assert headers[0] == "─── Hippeis Management ───"


def test_help_compose_uses_two_column_rows_for_bindings() -> None:
    source = inspect.getsource(HelpScreen.compose)
    assert 'with Horizontal(classes="help-row")' in source
    assert 'Label(key, classes="help-key")' in source
    assert 'Label(desc, classes="help-desc")' in source


def test_help_lists_core_bindings() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    # Hippeis management
    assert "q" in entries
    assert "Space" in entries
    assert "v" in entries
    assert "r" in entries
    assert "Ctrl+r" in entries
    assert "Ctrl+Alt+r" in entries
    assert "t" in entries
    assert "Ctrl+t" in entries
    assert "y" in entries
    assert "p" in entries
    assert "Ctrl+p" in entries
    assert "a" in entries
    assert "Ctrl+a" in entries
    assert "s" in entries
    assert "d" in entries
    assert "g" in entries
    assert "Ctrl+g" in entries
    assert "h" in entries
    assert "Ctrl+k" in entries
    assert "Ctrl+Alt+k" in entries
    assert "z" in entries
    assert "b" in entries
    assert "n" in entries
    assert "m" in entries
    assert "Ctrl+Alt+m" in entries

    # Interact panel
    assert "Ctrl+s" in entries
    assert "Ctrl+w" in entries
    assert "Ctrl+u" in entries
    assert "Ctrl+y" in entries
    assert "Ctrl+a / Ctrl+e" in entries
    assert "Alt+b / Alt+f" in entries
    assert "Alt+d / Alt+Backspace" in entries
    assert "↑/↓" in entries

    # Navigation
    assert "Tab" in entries
    assert "Enter" in entries
    assert "j / k (agent list)" in entries
    assert "Esc" in entries
    assert "Ctrl+Enter" in entries
    assert "Ctrl+o" in entries

    # Panels & settings
    assert "1" in entries
    assert "2" in entries
    assert "3" in entries
    assert "4" in entries
    assert "F4" in entries
    assert "F5" in entries
    assert "F6" in entries
    assert "F8" in entries
    assert "F10" in entries
    assert "?" in entries


def test_help_orders_agent_management_by_qwerty() -> None:
    start = _HELP_BINDINGS.index(("", "─── Hippeis Management ───")) + 1
    end = _HELP_BINDINGS.index(("", "─── Navigation ───"))
    keys = [key for key, _desc in _HELP_BINDINGS[start:end]]

    assert keys == [
        "q",
        "Space",
        "v",
        "r",
        "Ctrl+r",
        "Ctrl+Alt+r",
        "t",
        "Ctrl+t",
        "y",
        "p",
        "Ctrl+p",
        "a",
        "Ctrl+a",
        "s",
        "d",
        "g",
        "Ctrl+g",
        "h",
        "Ctrl+k",
        "Ctrl+Alt+k",
        "z",
        "b",
        "n",
        "m",
        "Ctrl+Alt+m",
    ]


def test_help_orders_interact_panel_by_qwerty() -> None:
    start = _HELP_BINDINGS.index(("", "─── Interact Panel ───")) + 1
    end = _HELP_BINDINGS.index(("", "─── Dialogs ───"))
    keys = [key for key, _desc in _HELP_BINDINGS[start:end]]

    assert keys == [
        "Ctrl+a / Ctrl+e",
        "Ctrl+s",
        "Ctrl+w",
        "Ctrl+u",
        "Ctrl+y",
        "Ctrl+k",
        "Alt+b / Alt+f",
        "Alt+d / Alt+Backspace",
        "↑/↓",
    ]


def test_help_orders_panels_settings_by_number_then_fkey() -> None:
    start = _HELP_BINDINGS.index(("", "─── Panels & Settings ───")) + 1
    keys = [key for key, _desc in _HELP_BINDINGS[start:]]

    assert keys == [
        "1",
        "2",
        "3",
        "4",
        "F4",
        "F5",
        "F6",
        "F8",
        "F10",
        "?",
    ]


def test_help_lists_dialog_bindings() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}
    # Dialog-specific contextual bindings
    assert "Esc" in entries  # close dialog
    assert "i (review)" in entries
    assert "Ctrl+s (tasks)" in entries
    assert "Ctrl+s (message)" in entries
    assert "Ctrl+w (message)" in entries
    assert "Alt+1–4 (message)" in entries
    assert "y / n / Enter (kill)" in entries


def test_help_no_stale_bindings() -> None:
    keys = {key for key, _desc in _HELP_BINDINGS if key}
    # These old keys should not be present
    assert "Ctrl+k (tmux row)" not in keys
    assert "k" not in keys
    assert "Ctrl+q" not in keys
    assert "i" not in keys
    assert "Ctrl+b" not in keys
    assert "Ctrl+m" not in keys


def test_help_section_count() -> None:
    headers = [desc for key, desc in _HELP_BINDINGS if not key]
    assert len(headers) == 5
    assert headers == [
        "─── Hippeis Management ───",
        "─── Navigation ───",
        "─── Interact Panel ───",
        "─── Dialogs ───",
        "─── Panels & Settings ───",
    ]
