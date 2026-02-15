"""Tests for dashboard keybinding behavior."""

from zeus.dashboard.app import ZeusApp


def test_numeric_panel_toggles_are_priority_bindings() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}

    for key in ("1", "2", "3", "4"):
        assert key in bindings
        assert bindings[key].priority is True
