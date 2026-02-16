"""Tests for rename behavior in dashboard actions."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow


def _agent(name: str = "old") -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name=name,
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
    )


def test_do_rename_agent_preserves_priority_on_new_name(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("old")
    app._agent_priorities = {"old": 2}

    saved_overrides: list[dict[str, str]] = []
    saved_priorities: list[bool] = []
    notices: list[str] = []
    polled: list[bool] = []

    monkeypatch.setattr("zeus.dashboard.app.load_names", lambda: {})
    monkeypatch.setattr(
        "zeus.dashboard.app.save_names",
        lambda overrides: saved_overrides.append(dict(overrides)),
    )
    monkeypatch.setattr(app, "_save_priorities", lambda: saved_priorities.append(True))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))

    app.do_rename_agent(agent, "new")

    assert saved_overrides[-1] == {"/tmp/kitty-1:1": "new"}
    assert app._agent_priorities == {"new": 2}
    assert saved_priorities == [True]
    assert notices[-1] == "Renamed: old → new"
    assert polled == [True]


def test_do_rename_agent_without_explicit_priority_keeps_priority_map(monkeypatch) -> None:
    app = ZeusApp()
    agent = _agent("old")
    app._agent_priorities = {"other": 1}

    saved_priorities: list[bool] = []

    monkeypatch.setattr("zeus.dashboard.app.load_names", lambda: {})
    monkeypatch.setattr("zeus.dashboard.app.save_names", lambda _overrides: None)
    monkeypatch.setattr(app, "_save_priorities", lambda: saved_priorities.append(True))
    monkeypatch.setattr(app, "notify", lambda _msg, timeout=3: None)
    monkeypatch.setattr(app, "poll_and_update", lambda: None)

    app.do_rename_agent(agent, "new")

    assert app._agent_priorities == {"other": 1}
    assert saved_priorities == []
