"""Tests for dashboard help bindings content."""

from zeus.dashboard.screens import _HELP_BINDINGS


def test_help_lists_text_area_navigation_commands() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Ctrl+a / Ctrl+e"] == "Move cursor to line start / end"
    assert entries["Alt+b / Alt+f"] == "Move cursor one word left / right"
    assert entries["Ctrl+b"] == (
        "Broadcast block between %%%% markers to active peers"
    )
    assert entries["Ctrl+m"] == (
        "Send block between %%%% markers to one selected active agent"
    )
    assert entries["c"] == "New agent"
    assert entries["n"] == "Edit notes for selected agent"

    up_down_desc = entries["↑/↓"]
    assert "visual top/bottom" in up_down_desc
    assert "history" in up_down_desc


def test_help_groups_global_shortcuts_before_interact_section() -> None:
    global_idx = _HELP_BINDINGS.index(("", "─── Global ───"))
    interact_idx = _HELP_BINDINGS.index(("", "─── Interact Panel ───"))

    global_entries = [
        ("1", "Toggle agent table"),
        ("2", "Toggle mini-map"),
        ("3", "Toggle sparkline charts"),
        ("4", "Toggle interact target band"),
    ]

    for entry in global_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert global_idx < idx < interact_idx


def test_help_groups_summary_shortcuts_under_agent_management() -> None:
    agent_mgmt_idx = _HELP_BINDINGS.index(("", "─── Agent Management ───"))
    settings_idx = _HELP_BINDINGS.index(("", "─── Settings ───"))

    mgmt_entries = [
        ("c", "New agent"),
        ("n", "Edit notes for selected agent"),
        ("Ctrl+b", "Broadcast block between %%%% markers to active peers"),
        ("Ctrl+m", "Send block between %%%% markers to one selected active agent"),
    ]

    for entry in mgmt_entries:
        idx = _HELP_BINDINGS.index(entry)
        assert agent_mgmt_idx < idx < settings_idx
