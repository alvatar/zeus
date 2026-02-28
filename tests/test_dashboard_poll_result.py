"""Tests for poll-result application pipeline."""

from zeus.dashboard.app import PollResult, ZeusApp
from zeus.models import AgentWindow, OpenAIUsageData, ProcessMetrics, State, UsageData


def _empty_result() -> PollResult:
    return PollResult(
        agents=[],
        usage=UsageData(),
        openai=OpenAIUsageData(),
        state_changed_at={},
        prev_states={},
        idle_since={},
        idle_notified=set(),
    )


def test_apply_poll_result_runs_helper_pipeline(monkeypatch) -> None:
    app = ZeusApp()
    result = _empty_result()
    calls: list[str] = []

    monkeypatch.setattr(app, "_commit_poll_state", lambda r: calls.append("commit"))
    monkeypatch.setattr(app, "_any_agent_state_changed", lambda old: calls.append("changed") or True)
    monkeypatch.setattr(app, "_update_action_needed", lambda old: calls.append("action-needed"))
    monkeypatch.setattr(app, "_process_aegis_state_transitions", lambda old: calls.append("aegis"))
    monkeypatch.setattr(app, "_collect_sparkline_samples", lambda: calls.append("sparkline"))
    monkeypatch.setattr(app, "_refresh_interact_if_state_changed", lambda old: calls.append("refresh-interact"))
    monkeypatch.setattr(app, "_update_usage_bars", lambda usage, openai: calls.append("usage"))
    monkeypatch.setattr(app, "_play_state_transition_alarms", lambda old: calls.append("alarm"))
    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: calls.append("render") or True)
    monkeypatch.setattr(app, "_pulse_agent_table", lambda: calls.append("pulse"))

    app._apply_poll_result(result)

    assert calls == [
        "commit",
        "changed",
        "action-needed",
        "aegis",
        "sparkline",
        "refresh-interact",
        "usage",
        "alarm",
        "render",
        "pulse",
    ]


def test_apply_poll_result_skips_pulse_when_render_short_circuits(monkeypatch) -> None:
    app = ZeusApp()
    result = _empty_result()
    calls: list[str] = []

    monkeypatch.setattr(app, "_commit_poll_state", lambda r: None)
    monkeypatch.setattr(app, "_any_agent_state_changed", lambda old: True)
    monkeypatch.setattr(app, "_update_action_needed", lambda old: None)
    monkeypatch.setattr(app, "_process_aegis_state_transitions", lambda old: None)
    monkeypatch.setattr(app, "_collect_sparkline_samples", lambda: None)
    monkeypatch.setattr(app, "_refresh_interact_if_state_changed", lambda old: None)
    monkeypatch.setattr(app, "_update_usage_bars", lambda usage, openai: None)
    monkeypatch.setattr(app, "_render_agent_table_and_status", lambda: False)
    monkeypatch.setattr(app, "_pulse_agent_table", lambda: calls.append("pulse"))

    app._apply_poll_result(result)

    assert calls == []


def test_play_state_transition_alarms_only_for_working_to_non_working(monkeypatch) -> None:
    app = ZeusApp()
    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )
    agent.state = State.IDLE
    app.agents = [agent]
    app._agent_alarm_enabled = {app._agent_alarm_key(agent)}

    plays: list[bool] = []
    monkeypatch.setattr(app, "_play_alarm_sound", lambda: plays.append(True) or True)

    app._play_state_transition_alarms({app._agent_key(agent): State.WORKING})
    assert plays == [True]

    plays.clear()
    app._play_state_transition_alarms({app._agent_key(agent): State.IDLE})
    assert plays == []


def test_play_alarm_sound_uses_paplay_with_default_75_percent_volume(monkeypatch) -> None:
    app = ZeusApp()
    popen_calls: list[list[str]] = []

    monkeypatch.setattr("zeus.dashboard.app.os.path.isfile", lambda _p: True)
    monkeypatch.setattr(
        "zeus.dashboard.app.shutil.which",
        lambda name: "/usr/sbin/paplay" if name == "paplay" else None,
    )

    def _popen(cmd, **_kwargs):  # noqa: ANN001
        popen_calls.append(list(cmd))
        return object()

    monkeypatch.setattr("zeus.dashboard.app.subprocess.Popen", _popen)

    ok = app._play_alarm_sound()

    assert ok is True
    assert len(popen_calls) == 1
    assert popen_calls[0][0] == "paplay"
    assert popen_calls[0][1] == "--volume=49152"
    assert popen_calls[0][2] == app._alarm_sound_path()


def test_poll_worker_reads_agent_metrics_from_window_pid(monkeypatch) -> None:
    app = ZeusApp()

    agent = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="alpha",
        pid=222,
        kitty_pid=111,
        cwd="/tmp/project",
    )

    metric_roots: list[int] = []

    monkeypatch.setattr("zeus.dashboard.app.discover_agents", lambda: [agent])
    monkeypatch.setattr("zeus.dashboard.app.build_pid_workspace_map", lambda: {})
    monkeypatch.setattr("zeus.dashboard.app.discover_tmux_sessions", lambda: [])
    monkeypatch.setattr("zeus.dashboard.app.read_usage", lambda: UsageData())
    monkeypatch.setattr("zeus.dashboard.app.read_openai_usage", lambda: OpenAIUsageData())
    monkeypatch.setattr("zeus.dashboard.app.get_screen_text", lambda a, full=False: "")
    monkeypatch.setattr("zeus.dashboard.app.detect_state", lambda s: State.IDLE)
    monkeypatch.setattr("zeus.dashboard.app.activity_signature", lambda s: "")
    monkeypatch.setattr("zeus.dashboard.app.parse_footer", lambda s: ("", 0.0, "", ""))
    monkeypatch.setattr(
        "zeus.dashboard.app.read_process_metrics",
        lambda root_pid: metric_roots.append(root_pid) or ProcessMetrics(),
    )
    monkeypatch.setattr("zeus.dashboard.app.match_tmux_to_agents", lambda a, t: None)
    monkeypatch.setattr("zeus.dashboard.app.backfill_tmux_owner_options", lambda a: None)

    captured: list[PollResult] = []
    monkeypatch.setattr(app, "call_from_thread", lambda fn, result: captured.append(result))

    ZeusApp._poll_worker.__wrapped__(app)

    assert metric_roots == [agent.pid]
    assert captured and captured[0].agents[0].proc_metrics == ProcessMetrics()
