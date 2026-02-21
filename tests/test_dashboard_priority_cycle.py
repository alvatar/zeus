"""Tests for instant priority cycling behavior."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
    )


def test_action_cycle_priority_renders_immediately_before_poll(monkeypatch) -> None:
    app = ZeusApp()
    app._agent_priorities = {}
    agent = _agent("alpha", 1)

    calls: list[str] = []
    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "_save_priorities", lambda: calls.append("save"))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: calls.append("render") or True,
    )
    monkeypatch.setattr(app, "poll_and_update", lambda: calls.append("poll"))
    monkeypatch.setattr(app, "_refresh_interact_panel", lambda: calls.append("refresh"))
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: True))

    app._interact_visible = False

    app.action_cycle_priority()

    assert app._agent_priorities["alpha"] == 2
    assert calls == ["save", "render", "poll"]


def test_action_cycle_priority_from_paused_clears_priority_entry(monkeypatch) -> None:
    app = ZeusApp()
    app._agent_priorities = {"alpha": 4}
    agent = _agent("alpha", 1)

    calls: list[str] = []
    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "_save_priorities", lambda: calls.append("save"))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: calls.append("render") or True,
    )
    monkeypatch.setattr(app, "poll_and_update", lambda: calls.append("poll"))
    monkeypatch.setattr(app, "_refresh_interact_panel", lambda: calls.append("refresh"))
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: True))

    app._interact_visible = True

    app.action_cycle_priority()

    assert app._agent_priorities == {}
    assert calls == ["save", "render", "poll", "refresh"]


def test_action_cycle_priority_skips_immediate_render_when_not_running(monkeypatch) -> None:
    app = ZeusApp()
    app._agent_priorities = {}
    agent = _agent("alpha", 1)

    calls: list[str] = []
    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: agent)
    monkeypatch.setattr(app, "_save_priorities", lambda: calls.append("save"))
    monkeypatch.setattr(
        app,
        "_render_agent_table_and_status",
        lambda: calls.append("render") or True,
    )
    monkeypatch.setattr(app, "poll_and_update", lambda: calls.append("poll"))
    monkeypatch.setattr(ZeusApp, "is_running", property(lambda _self: False))

    app._interact_visible = False

    app.action_cycle_priority()

    assert app._agent_priorities["alpha"] == 2
    assert calls == ["save", "poll"]
