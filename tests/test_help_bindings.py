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


def test_help_lists_text_area_navigation_commands() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Ctrl+a / Ctrl+e"] == (
        "Move to line start/end; at edge jump to prev/next line"
    )
    assert entries["Alt+b / Alt+f"] == "Move cursor one word left / right"
    assert entries["Alt+d / Alt+Backspace"] == "Delete word right / left"
    assert entries["Ctrl+k"] == "Kill to end-of-line (or delete line if empty)"
    assert entries["Ctrl+u"] == "Clear input"
    assert entries["Ctrl+y"] == (
        "Yank killed text (system clipboard, fallback local kill buffer)"
    )
    assert entries["Ctrl+b"] == (
        "Broadcast block between %%%% markers to active Hippeis"
    )
    assert entries["Ctrl+m"] == (
        "Send text between %%%% markers to selected target"
    )
    assert entries["Ctrl+k (tmux row)"] == "Kill tmux session process"
    assert entries["z"] == "Invoke Hippeus / Polemarch"
    assert entries["a"] == "Bring Hippeus under the Aegis"
    assert entries["n"] == "Queue next task for selected Hippeus"
    assert entries["g"] == "Send 'go ahead' to selected Hippeus"
    assert entries["t"] == "Edit tasks for selected Hippeus"
    assert entries["Ctrl+t"] == "Clear done tasks for selected Hippeus"
    assert entries["i"] == "Set/remove blocking dependency for selected Hippeus"
    assert "m" not in entries
    assert entries["1"] == "Toggle interact input area"

    up_down_desc = entries["↑/↓"]
    assert "visual top/bottom" in up_down_desc
    assert "history" in up_down_desc


def test_help_groups_global_shortcuts_in_last_section() -> None:
    global_idx = _HELP_BINDINGS.index(("", "─── Global ───"))

    global_entries = [
        ("1", "Toggle interact input area"),
        ("2", "Toggle mini-map"),
        ("3", "Toggle sparkline charts"),
        ("4", "Toggle interact target band"),
    ]

    headers = [idx for idx, (key, _desc) in enumerate(_HELP_BINDINGS) if not key]
    assert global_idx == headers[-1]

    for entry in global_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert idx > global_idx


def test_help_groups_summary_shortcuts_under_agent_management() -> None:
    agent_mgmt_idx = _HELP_BINDINGS.index(("", "─── Hippeis Management ───"))
    settings_idx = _HELP_BINDINGS.index(("", "─── Settings ───"))

    mgmt_entries = [
        ("z", "Invoke Hippeus / Polemarch"),
        ("a", "Bring Hippeus under the Aegis"),
        ("n", "Queue next task for selected Hippeus"),
        ("g", "Send 'go ahead' to selected Hippeus"),
        ("t", "Edit tasks for selected Hippeus"),
        ("Ctrl+t", "Clear done tasks for selected Hippeus"),
        ("i", "Set/remove blocking dependency for selected Hippeus"),
        ("Ctrl+b", "Broadcast block between %%%% markers to active Hippeis"),
        (
            "Ctrl+m",
            "Send text between %%%% markers to selected target",
        ),
        ("Ctrl+k (tmux row)", "Kill tmux session process"),
    ]

    for entry in mgmt_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert agent_mgmt_idx < idx < settings_idx


def test_help_lists_all_top_level_app_bindings() -> None:
    keys = {key for key, _desc in _HELP_BINDINGS if key}

    expected = {
        "q",
        "F10",
        "Tab",
        "Ctrl+Enter",
        "Ctrl+o",
        "z",
        "a",
        "n",
        "g",
        "t",
        "Ctrl+t",
        "i",
        "s",
        "k",
        "p",
        "r",
        "F5",
        "Ctrl+s",
        "Ctrl+w",
        "Ctrl+b",
        "Ctrl+m",
        "Ctrl+k (tmux row)",
        "1",
        "2",
        "3",
        "4",
        "F4",
        "F6",
        "F8",
        "?",
    }

    assert expected <= keys
    assert "Ctrl+q" not in keys


def test_help_lists_modal_only_bindings() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Esc (dialog)"] == "Close/cancel active dialog"
    assert entries["Ctrl+s (tasks dialog)"] == "Save tasks in Hippeus Tasks dialog"
    assert entries["Ctrl+s (message dialog)"] == "Send message in Hippeus Message dialog"
    assert entries["Ctrl+w (message dialog)"] == "Queue message in Hippeus Message dialog"
    assert entries["y / n / Enter (kill confirm)"] == (
        "Confirm or cancel kill confirmation dialogs"
    )
