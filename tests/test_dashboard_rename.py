"""Tests for rename behavior in dashboard actions."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import SubAgentScreen
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


def test_do_rename_agent_rejects_duplicate_name(monkeypatch) -> None:
    app = ZeusApp()
    target = _agent("old")
    existing = AgentWindow(
        kitty_id=2,
        socket="/tmp/kitty-1",
        name="taken",
        pid=102,
        kitty_pid=202,
        cwd="/tmp/project",
    )
    app.agents = [target, existing]

    notices: list[str] = []
    polls: list[bool] = []
    saved_overrides: list[dict[str, str]] = []

    monkeypatch.setattr("zeus.dashboard.app.load_names", lambda: {})
    monkeypatch.setattr(
        "zeus.dashboard.app.save_names",
        lambda overrides: saved_overrides.append(dict(overrides)),
    )
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polls.append(True))

    ok = app.do_rename_agent(target, "taken")

    assert ok is False
    assert saved_overrides == []
    assert polls == []
    assert notices[-1] == "Name already exists: taken"


def test_do_spawn_subagent_rejects_duplicate_name(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent")
    taken = AgentWindow(
        kitty_id=2,
        socket="/tmp/kitty-1",
        name="taken",
        pid=102,
        kitty_pid=202,
        cwd="/tmp/project",
    )
    app.agents = [parent, taken]

    notices: list[str] = []
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    def _spawn_fail(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("must not spawn")

    monkeypatch.setattr("zeus.dashboard.app.spawn_subagent", _spawn_fail)

    app.do_spawn_subagent(parent, "taken")

    assert notices[-1] == "Name already exists: taken"


def test_action_spawn_subagent_recovers_hidden_session_path(monkeypatch) -> None:
    app = ZeusApp()
    hidden = AgentWindow(
        kitty_id=0,
        socket="",
        name="shadow",
        pid=101,
        kitty_pid=0,
        cwd="/tmp/project",
        agent_id="agent-hidden",
        backend="tmux-hidden",
        tmux_session="hidden-agent",
    )
    app.agents = [hidden]

    pushed: list[object] = []
    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: hidden)
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_hidden_session_path",
        lambda _sess: "/tmp/hidden-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda agent: (agent.session_path, "env"),
    )
    monkeypatch.setattr("zeus.dashboard.app.os.path.isfile", lambda path: path == "/tmp/hidden-session.jsonl")
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.action_spawn_subagent()

    assert hidden.session_path == "/tmp/hidden-session.jsonl"
    assert pushed
    assert isinstance(pushed[0], SubAgentScreen)
    assert notices == []


def test_action_spawn_subagent_uses_runtime_source_even_when_cwd_shared(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent")
    sibling = AgentWindow(
        kitty_id=2,
        socket="/tmp/kitty-1",
        name="sibling",
        pid=102,
        kitty_pid=202,
        cwd="/tmp/project",
    )
    app.agents = [parent, sibling]

    pushed: list[object] = []
    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: parent)
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda _agent: ("/tmp/runtime-session.jsonl", "runtime"),
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.os.path.isfile",
        lambda path: path == "/tmp/runtime-session.jsonl",
    )
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.action_spawn_subagent()

    assert pushed
    assert isinstance(pushed[0], SubAgentScreen)
    assert parent.session_path == "/tmp/runtime-session.jsonl"
    assert notices == []


def test_action_spawn_subagent_blocks_cwd_fallback_when_cwd_shared(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent")
    sibling = AgentWindow(
        kitty_id=2,
        socket="/tmp/kitty-1",
        name="sibling",
        pid=102,
        kitty_pid=202,
        cwd="/tmp/project",
    )
    app.agents = [parent, sibling]

    pushed: list[object] = []
    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: parent)
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda _agent: ("/tmp/fallback-session.jsonl", "cwd"),
    )
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.action_spawn_subagent()

    assert pushed == []
    assert notices[-1].startswith("Cannot reliably fork this legacy Hippeus")


def test_name_uniqueness_checks_are_case_insensitive() -> None:
    app = ZeusApp()
    app.agents = [
        AgentWindow(
            kitty_id=2,
            socket="/tmp/kitty-1",
            name="Taken",
            pid=102,
            kitty_pid=202,
            cwd="/tmp/project",
        )
    ]

    assert app._is_agent_name_taken("taken") is True
    assert app._is_agent_name_taken("TAKEN") is True
