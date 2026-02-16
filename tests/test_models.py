"""Tests for data models."""

from zeus.models import (
    State, TmuxSession, ProcessMetrics, AgentWindow,
    UsageData, OpenAIUsageData,
)


def test_state_enum_values():
    assert State.WORKING == "WORKING"
    assert State.IDLE == "IDLE"
    assert State.WORKING.value == "WORKING"


def test_agent_window_defaults():
    a = AgentWindow(
        kitty_id=1, socket="/tmp/kitty-123", name="test",
        pid=100, kitty_pid=99, cwd="/home/user",
    )
    assert a.agent_id == ""
    assert a.state == State.IDLE
    assert a.model == ""
    assert a.role == ""
    assert a.session_path == ""
    assert a.tmux_sessions == []
    assert a.proc_metrics.cpu_pct == 0.0
    assert a._screen_text == ""


def test_tmux_session_defaults():
    s = TmuxSession(name="dev", command="bash", cwd="/tmp")
    assert s.created == 0
    assert s.attached is False
    assert s.owner_id == ""
    assert s.env_agent_id == ""
    assert s.agent_id == ""
    assert s.role == ""
    assert s.phalanx_id == ""
    assert s.match_source == ""


def test_usage_data_defaults():
    u = UsageData()
    assert u.session_pct == 0.0
    assert u.available is False


def test_openai_usage_data_defaults():
    o = OpenAIUsageData()
    assert o.requests_pct == 0.0
    assert o.available is False


def test_process_metrics_defaults():
    p = ProcessMetrics()
    assert p.cpu_pct == 0.0
    assert p.io_read_bps == 0.0
