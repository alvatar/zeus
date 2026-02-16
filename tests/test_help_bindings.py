"""Tests for dashboard help bindings content."""

from zeus.dashboard.screens import _HELP_BINDINGS


def test_help_lists_text_area_navigation_commands() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Ctrl+a / Ctrl+e"] == "Move cursor to line start / end"
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
        "Send block between %%%% markers to one selected active Hippeus"
    )
    assert entries["c"] == "Muster Hippeus"
    assert entries["a"] == "Bring Hippeus under the Aegis"
    assert entries["n"] == "Edit notes for selected Hippeus"
    assert entries["Ctrl+i"] == "Set/remove blocking dependency for selected Hippeus"

    up_down_desc = entries["↑/↓"]
    assert "visual top/bottom" in up_down_desc
    assert "history" in up_down_desc


def test_help_groups_global_shortcuts_before_interact_section() -> None:
    global_idx = _HELP_BINDINGS.index(("", "─── Global ───"))
    interact_idx = _HELP_BINDINGS.index(("", "─── Interact Panel ───"))

    global_entries = [
        ("2", "Toggle mini-map"),
        ("3", "Toggle sparkline charts"),
        ("4", "Toggle interact target band"),
    ]

    for entry in global_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert global_idx < idx < interact_idx


def test_help_groups_summary_shortcuts_under_agent_management() -> None:
    agent_mgmt_idx = _HELP_BINDINGS.index(("", "─── Hippeis Management ───"))
    settings_idx = _HELP_BINDINGS.index(("", "─── Settings ───"))

    mgmt_entries = [
        ("c", "Muster Hippeus"),
        ("a", "Bring Hippeus under the Aegis"),
        ("n", "Edit notes for selected Hippeus"),
        ("Ctrl+i", "Set/remove blocking dependency for selected Hippeus"),
        ("Ctrl+b", "Broadcast block between %%%% markers to active Hippeis"),
        ("Ctrl+m", "Send block between %%%% markers to one selected active Hippeus"),
    ]

    for entry in mgmt_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert agent_mgmt_idx < idx < settings_idx


def test_help_lists_all_top_level_app_bindings() -> None:
    keys = {key for key, _desc in _HELP_BINDINGS if key}

    expected = {
        "q",
        "Ctrl+q",
        "F10",
        "Tab",
        "Ctrl+Enter",
        "Ctrl+o",
        "c",
        "a",
        "n",
        "Ctrl+i",
        "s",
        "k",
        "p",
        "r",
        "F5",
        "Ctrl+s",
        "Ctrl+w",
        "Ctrl+b",
        "Ctrl+m",
        "2",
        "3",
        "4",
        "F4",
        "F6",
        "F8",
        "?",
    }

    assert expected <= keys


def test_help_lists_modal_only_bindings() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Esc (dialog)"] == "Close/cancel active dialog"
    assert entries["Ctrl+s (notes dialog)"] == "Save notes in Hippeus Notes dialog"
    assert entries["y / n / Enter (kill confirm)"] == (
        "Confirm or cancel kill confirmation dialogs"
    )
