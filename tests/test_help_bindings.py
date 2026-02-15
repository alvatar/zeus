"""Tests for dashboard help bindings content."""

from zeus.dashboard.screens import _HELP_BINDINGS


def test_help_lists_text_area_navigation_commands() -> None:
    entries = {key: desc for key, desc in _HELP_BINDINGS if key}

    assert entries["Ctrl+a / Ctrl+e"] == "Move cursor to line start / end"
    assert entries["Alt+b / Alt+f"] == "Move cursor one word left / right"
    assert entries["Ctrl+b"] == (
        "Broadcast selected agent summary to active peers"
    )

    up_down_desc = entries["↑/↓"]
    assert "visual top/bottom" in up_down_desc
    assert "history" in up_down_desc
