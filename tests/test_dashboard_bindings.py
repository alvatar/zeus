"""Tests for dashboard keybinding behavior."""

from zeus.dashboard.app import ZeusApp


def test_numeric_panel_toggles_are_priority_bindings() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}

    for key in ("1", "2", "3", "4"):
        assert key in bindings
        assert bindings[key].priority is True


def test_agent_management_summary_bindings_use_plain_b_and_m() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "b" in bindings
    assert bindings["b"].action == "broadcast_summary"
    assert bindings["b"].priority is False
    assert "m" in bindings
    assert bindings["m"].action == "direct_summary"
    assert bindings["m"].priority is False
    assert "ctrl+t" in bindings
    assert bindings["ctrl+t"].priority is True
    assert "ctrl+b" not in bindings
    assert "ctrl+m" not in bindings


def test_dependency_binding_uses_plain_d() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "d" in bindings
    assert bindings["d"].action == "toggle_dependency"


def test_toggle_interact_input_binding_action() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert bindings["1"].action == "toggle_interact_input"


def test_clear_done_tasks_binding_action() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert bindings["ctrl+t"].action == "clear_done_tasks"


def test_kill_tmux_session_binding_action() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert bindings["ctrl+k"].action == "kill_tmux_session"


def test_agent_management_keys_include_z_a_n_g_t_e_d_l_b_and_m() -> None:
    bindings = {binding.key: binding for binding in ZeusApp.BINDINGS}
    assert "z" in bindings
    assert bindings["z"].action == "new_agent"
    assert "a" in bindings
    assert bindings["a"].action == "toggle_aegis"
    assert "n" in bindings
    assert bindings["n"].action == "queue_next_task"
    assert "g" in bindings
    assert bindings["g"].action == "go_ahead"
    assert "t" in bindings
    assert bindings["t"].action == "agent_tasks"
    assert "e" in bindings
    assert bindings["e"].action == "expand_output"
    assert "d" in bindings
    assert bindings["d"].action == "toggle_dependency"
    assert "l" in bindings
    assert bindings["l"].action == "last_sent_message"
    assert "b" in bindings
    assert bindings["b"].action == "broadcast_summary"
    assert "m" in bindings
    assert bindings["m"].action == "direct_summary"
    assert "i" not in bindings
    assert "h" not in bindings
    assert "c" not in bindings
    assert "ctrl+q" not in bindings
