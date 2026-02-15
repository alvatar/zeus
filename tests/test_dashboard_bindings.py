"""Tests for dashboard keybinding behavior."""

from zeus.dashboard.app import ZeusApp


def test_numeric_panel_toggles_are_priority_bindings() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}

    for key in ("1", "2", "3", "4"):
        assert key in bindings
        assert bindings[key].priority is True


def test_agent_management_summary_bindings_are_priority() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "ctrl+b" in bindings
    assert bindings["ctrl+b"].priority is True
    assert "ctrl+m" in bindings
    assert bindings["ctrl+m"].priority is True


def test_dependency_binding_is_priority() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "ctrl+i" in bindings
    assert bindings["ctrl+i"].priority is True


def test_agent_management_keys_include_c_and_n() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "c" in bindings
    assert bindings["c"].action == "new_agent"
    assert "n" in bindings
    assert bindings["n"].action == "agent_notes"
