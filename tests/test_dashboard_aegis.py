"""Tests for Aegis lifecycle behavior."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, State


class _FakeTimer:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _agent(name: str, kitty_id: int) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def _new_app() -> ZeusApp:
    app = ZeusApp()
    app._agent_dependencies = {}
    app._agent_priorities = {}
    app._aegis_enabled = set()
    app._aegis_modes = {}
    app._aegis_delay_timers = {}
    app._aegis_check_timers = {}
    return app


def test_aegis_post_check_delay_is_20_seconds() -> None:
    assert ZeusApp._AEGIS_CHECK_S == 20.0


def test_toggle_aegis_enables_and_disables_selected_hippeus(monkeypatch) -> None:
    app = _new_app()
    hippeus = _agent("alpha", 1)
    key = app._agent_key(hippeus)

    notices: list[str] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: hippeus)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: renders.append(True) or True)
    app._interact_visible = False

    app.action_toggle_aegis()

    assert key in app._aegis_enabled
    assert app._aegis_modes[key] == app._AEGIS_MODE_ARMED
    assert notices[-1] == "Aegis enabled: alpha"
    assert renders == [True]

    app.action_toggle_aegis()

    assert key not in app._aegis_enabled
    assert key not in app._aegis_modes
    assert notices[-1] == "Aegis disabled: alpha"
    assert renders == [True, True]


def test_toggle_aegis_rejects_blocked_or_paused_hippeus(monkeypatch) -> None:
    app = _new_app()
    blocker = _agent("blocker", 2)
    blocked = _agent("blocked", 1)
    paused = _agent("paused", 3)

    app.agents = [blocked, blocker, paused]
    app._agent_dependencies[app._agent_dependency_key(blocked)] = app._agent_dependency_key(
        blocker
    )
    app._agent_priorities[paused.name] = 4

    notices: list[str] = []
    renders: list[bool] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=2: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: renders.append(True) or True,
    )
    app._interact_visible = False

    monkeypatch.setattr(app, "_get_selected_agent", lambda: blocked)
    app.action_toggle_aegis()
    assert app._agent_key(blocked) not in app._aegis_enabled
    assert notices[-1] == "Aegis unavailable for blocked/paused Hippeus: blocked"

    monkeypatch.setattr(app, "_get_selected_agent", lambda: paused)
    app.action_toggle_aegis()
    assert app._agent_key(paused) not in app._aegis_enabled
    assert notices[-1] == "Aegis unavailable for blocked/paused Hippeus: paused"

    assert renders == []


def test_reconcile_aegis_disables_blocked_and_paused_agents() -> None:
    app = _new_app()
    blocker = _agent("blocker", 1)
    blocked = _agent("blocked", 2)
    paused = _agent("paused", 3)
    normal = _agent("normal", 4)

    app.agents = [blocker, blocked, paused, normal]
    app._agent_dependencies[app._agent_dependency_key(blocked)] = app._agent_dependency_key(
        blocker
    )
    app._agent_priorities[paused.name] = 4

    blocked_key = app._agent_key(blocked)
    paused_key = app._agent_key(paused)
    normal_key = app._agent_key(normal)

    app._aegis_enabled.update({blocked_key, paused_key, normal_key})
    app._aegis_modes[blocked_key] = app._AEGIS_MODE_ARMED
    app._aegis_modes[paused_key] = app._AEGIS_MODE_ARMED
    app._aegis_modes[normal_key] = app._AEGIS_MODE_ARMED

    blocked_delay = _FakeTimer()
    paused_check = _FakeTimer()
    app._aegis_delay_timers[blocked_key] = blocked_delay
    app._aegis_check_timers[paused_key] = paused_check

    app._reconcile_aegis_agents({app._agent_key(agent) for agent in app.agents})

    assert blocked_key not in app._aegis_enabled
    assert paused_key not in app._aegis_enabled
    assert normal_key in app._aegis_enabled
    assert blocked_delay.stopped is True
    assert paused_check.stopped is True


def test_aegis_state_bg_uses_bright_and_dim_variants() -> None:
    app = _new_app()
    hippeus = _agent("alpha", 1)
    key = app._agent_key(hippeus)

    assert app._aegis_state_bg(key) == "#000000"

    app._aegis_enabled.add(key)
    app._aegis_modes[key] = app._AEGIS_MODE_ARMED
    assert app._aegis_state_bg(key) == app._AEGIS_ROW_BG

    app._aegis_modes[key] = app._AEGIS_MODE_HALTED
    assert app._aegis_state_bg(key) == app._AEGIS_ROW_BG_DIM


def test_aegis_halted_color_uses_bland_yellow() -> None:
    assert ZeusApp._AEGIS_ROW_BG_DIM == "#8a8450"


def test_aegis_transition_schedules_single_delay_timer(monkeypatch) -> None:
    app = _new_app()
    hippeus = _agent("alpha", 1)
    hippeus.state = State.IDLE
    app.agents = [hippeus]
    key = app._agent_key(hippeus)
    app._aegis_enabled.add(key)
    app._aegis_modes[key] = app._AEGIS_MODE_ARMED

    timers: list[tuple[float, object]] = []

    def _set_timer(delay: float, callback: object) -> _FakeTimer:
        timers.append((delay, callback))
        return _FakeTimer()

    monkeypatch.setattr(app, "set_timer", _set_timer)

    old_states = {key: State.WORKING}
    app._process_aegis_state_transitions(old_states)

    assert app._aegis_modes[key] == app._AEGIS_MODE_PENDING_DELAY
    assert len(timers) == 1
    assert timers[0][0] == app._AEGIS_DELAY_S

    app._process_aegis_state_transitions(old_states)
    assert len(timers) == 1


def test_aegis_delay_sends_prompt_once_and_starts_post_check(monkeypatch) -> None:
    app = _new_app()
    hippeus = _agent("alpha", 1)
    hippeus.state = State.IDLE
    app.agents = [hippeus]
    key = app._agent_key(hippeus)
    app._aegis_enabled.add(key)
    app._aegis_modes[key] = app._AEGIS_MODE_PENDING_DELAY

    sent: list[tuple[str, str]] = []
    timers: list[tuple[float, object]] = []

    monkeypatch.setattr(
        app,
        "_send_text_to_agent",
        lambda agent, text: sent.append((agent.name, text)),
    )
    monkeypatch.setattr(
        app,
        "set_timer",
        lambda delay, callback: timers.append((delay, callback)) or _FakeTimer(),
    )

    app._on_aegis_delay_elapsed(key)

    assert sent == [("alpha", app._AEGIS_PROMPT)]
    assert app._aegis_modes[key] == app._AEGIS_MODE_POST_CHECK
    assert len(timers) == 1
    assert timers[0][0] == app._AEGIS_CHECK_S

    app._on_aegis_delay_elapsed(key)
    assert sent == [("alpha", app._AEGIS_PROMPT)]


def test_aegis_post_check_rearms_only_if_working_again() -> None:
    app = _new_app()
    hippeus = _agent("alpha", 1)
    key = app._agent_key(hippeus)
    app.agents = [hippeus]
    app._aegis_enabled.add(key)

    app._aegis_modes[key] = app._AEGIS_MODE_POST_CHECK
    hippeus.state = State.WORKING
    app._on_aegis_check_elapsed(key)
    assert app._aegis_modes[key] == app._AEGIS_MODE_ARMED

    app._aegis_modes[key] = app._AEGIS_MODE_POST_CHECK
    hippeus.state = State.IDLE
    app._on_aegis_check_elapsed(key)
    assert app._aegis_modes[key] == app._AEGIS_MODE_HALTED
