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


def test_toggle_aegis_enables_and_disables_selected_hippeus(monkeypatch) -> None:
    app = ZeusApp()
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


def test_aegis_transition_schedules_single_delay_timer(monkeypatch) -> None:
    app = ZeusApp()
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
    app = ZeusApp()
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
    app = ZeusApp()
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
