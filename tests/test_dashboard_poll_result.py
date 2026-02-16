"""Tests for poll-result application pipeline."""

from zeus.dashboard.app import PollResult, ZeusApp
from zeus.models import OpenAIUsageData, UsageData


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
