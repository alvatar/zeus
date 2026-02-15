"""Tests for dashboard dependency helpers."""

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow


def _agent(name: str, kitty_id: int, agent_id: str) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def test_would_create_dependency_cycle_detects_back_edge() -> None:
    app = ZeusApp()
    app._agent_dependencies = {
        "b": "c",
        "c": "d",
    }

    assert app._would_create_dependency_cycle("a", "b") is False

    app._agent_dependencies["d"] = "a"
    assert app._would_create_dependency_cycle("a", "b") is True


def test_reconcile_agent_dependencies_clears_missing_after_two_polls(monkeypatch) -> None:
    app = ZeusApp()
    blocked = _agent("blocked", 1, agent_id="blocked-id")
    app.agents = [blocked]
    app._agent_dependencies = {"blocked-id": "missing-id"}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    saves: list[dict[str, str]] = []
    monkeypatch.setattr(app, "_save_agent_dependencies", lambda: saves.append(dict(app._agent_dependencies)))

    app._reconcile_agent_dependencies()
    assert app._agent_dependencies == {"blocked-id": "missing-id"}
    assert app._dependency_missing_polls == {"blocked-id": 1}
    assert notices == []

    app._reconcile_agent_dependencies()
    assert app._agent_dependencies == {}
    assert app._dependency_missing_polls == {}
    assert notices[-1] == "Dependency cleared for blocked: blocker missing"
    assert saves[-1] == {}


def test_do_set_dependency_rejects_cycle(monkeypatch) -> None:
    app = ZeusApp()
    a = _agent("a", 1, agent_id="a-id")
    b = _agent("b", 2, agent_id="b-id")
    app.agents = [a, b]
    app._agent_dependencies = {"b-id": "a-id"}

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: None)

    app.do_set_dependency(a, "b-id")

    assert app._agent_dependencies == {"b-id": "a-id"}
    assert notices[-1] == "Dependency rejected: would create cycle"
