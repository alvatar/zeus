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
    assert "ctrl+t" in bindings
    assert bindings["ctrl+t"].priority is True


def test_dependency_binding_is_priority() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "ctrl+i" in bindings
    assert bindings["ctrl+i"].priority is True


def test_toggle_interact_input_binding_action() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert bindings["1"].action == "toggle_interact_input"


def test_clear_done_tasks_binding_action() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert bindings["ctrl+t"].action == "clear_done_tasks"


def test_agent_management_keys_include_c_a_h_t_and_m() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "c" in bindings
    assert bindings["c"].action == "new_agent"
    assert "a" in bindings
    assert bindings["a"].action == "toggle_aegis"
    assert "h" in bindings
    assert bindings["h"].action == "queue_next_task"
    assert "t" in bindings
    assert bindings["t"].action == "agent_tasks"
    assert "m" in bindings
    assert bindings["m"].action == "agent_message"
