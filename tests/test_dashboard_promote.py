"""Tests for Ctrl+P promotion flow in dashboard actions."""

from types import SimpleNamespace

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import ConfirmPromoteScreen
from zeus.models import AgentWindow, TmuxSession


def _agent(
    name: str,
    *,
    kitty_id: int,
    agent_id: str,
    parent_id: str = "",
    role: str = "",
) -> AgentWindow:
    return AgentWindow(
        kitty_id=kitty_id,
        socket="/tmp/kitty-1",
        name=name,
        pid=100 + kitty_id,
        kitty_pid=200 + kitty_id,
        cwd="/tmp/project",
        agent_id=agent_id,
        parent_id=parent_id,
        role=role,
    )


def _hoplite_tmux(
    *,
    name: str = "hoplite-a",
    owner_id: str = "polemarch-1",
    agent_id: str = "hoplite-1",
) -> TmuxSession:
    return TmuxSession(
        name=name,
        command="",
        cwd="/tmp/project",
        owner_id=owner_id,
        role="hoplite",
        phalanx_id=f"phalanx-{owner_id}",
        agent_id=agent_id,
    )


def test_action_promote_selected_pushes_confirm_for_sub_hippeus(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent", kitty_id=1, agent_id="parent-1")
    child = _agent(
        "child",
        kitty_id=2,
        agent_id="child-1",
        parent_id="parent-1",
    )
    app.agents = [parent, child]

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: None)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: child)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_promote_selected()

    assert pushed
    assert isinstance(pushed[0], ConfirmPromoteScreen)
    assert pushed[0].agent is child
    assert pushed[0].promote_to == "hippeus"


def test_action_promote_selected_pushes_confirm_for_top_level_hippeus(monkeypatch) -> None:
    app = ZeusApp()
    top = _agent("top", kitty_id=1, agent_id="top-1", role="hippeus")
    app.agents = [top]

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: None)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: top)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_promote_selected()

    assert pushed
    assert isinstance(pushed[0], ConfirmPromoteScreen)
    assert pushed[0].agent is top
    assert pushed[0].promote_to == "polemarch"


def test_action_promote_selected_rejects_agent_already_polemarch(monkeypatch) -> None:
    app = ZeusApp()
    polemarch = _agent("planner", kitty_id=1, agent_id="planner-1", role="polemarch")
    app.agents = [polemarch]

    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: None)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: polemarch)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.action_promote_selected()

    assert notices[-1] == "planner is already a Polemarch"


def test_do_promote_sub_hippeus_relaunches_as_top_level_hippeus(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = False
    child = _agent(
        "child",
        kitty_id=2,
        agent_id="child-1",
        parent_id="parent-1",
    )
    child.workspace = "3"

    notices: list[str] = []
    closed: list[str] = []
    timers: list[tuple[float, object]] = []
    popen_calls: list[tuple[list[str], dict[str, str]]] = []
    moved: list[tuple[int, str, float]] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "set_timer", lambda delay, cb: timers.append((delay, cb)))
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda _agent: ("/tmp/child-session.jsonl", "env"),
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.os.path.isfile",
        lambda path: path == "/tmp/child-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.close_window",
        lambda agent: closed.append(f"{agent.socket}:{agent.kitty_id}"),
    )

    def _popen(cmd, **kwargs):  # noqa: ANN001
        popen_calls.append((list(cmd), dict(kwargs["env"])))
        return SimpleNamespace(pid=999)

    monkeypatch.setattr("zeus.dashboard.app.subprocess.Popen", _popen)
    monkeypatch.setattr(
        "zeus.dashboard.app.move_pid_to_workspace_and_focus_later",
        lambda pid, ws, delay: moved.append((pid, ws, delay)),
    )

    ok = app.do_promote_sub_hippeus(child)

    assert ok is True
    assert closed == ["/tmp/kitty-1:2"]

    assert popen_calls
    cmd, env = popen_calls[-1]
    assert cmd[:5] == ["kitty", "--directory", "/tmp/project", "--hold", "bash"]
    assert env["ZEUS_AGENT_NAME"] == "child"
    assert env["ZEUS_AGENT_ID"] == "child-1"
    assert env["ZEUS_ROLE"] == "hippeus"
    assert env["ZEUS_SESSION_PATH"] == "/tmp/child-session.jsonl"
    assert "ZEUS_PARENT_ID" not in env
    assert "ZEUS_PHALANX_ID" not in env

    assert moved == [(999, "3", 0.5)]
    assert notices[-1] == "Promoted sub-Hippeus to Hippeus: child"
    assert timers and timers[-1][0] == 1.0


def test_do_promote_sub_hippeus_rejects_ambiguous_cwd_fallback(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent", kitty_id=1, agent_id="parent-1")
    child = _agent(
        "child",
        kitty_id=2,
        agent_id="child-1",
        parent_id="parent-1",
    )
    sibling = _agent("sibling", kitty_id=3, agent_id="sibling-1")
    sibling.cwd = child.cwd
    app.agents = [parent, child, sibling]

    notices: list[str] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda _agent: ("/tmp/fallback-session.jsonl", "cwd"),
    )

    ok = app.do_promote_sub_hippeus(child)

    assert ok is False
    assert notices[-1].startswith("Cannot reliably promote this legacy sub-Hippeus")


def test_do_promote_hippeus_to_polemarch_relaunches_with_confirmation_target(
    monkeypatch,
) -> None:
    app = ZeusApp()
    app._interact_visible = False
    top = _agent("top", kitty_id=1, agent_id="top-1", role="hippeus")
    top.workspace = "5"

    notices: list[str] = []
    closed: list[str] = []
    timers: list[tuple[float, object]] = []
    popen_calls: list[tuple[list[str], dict[str, str]]] = []
    moved: list[tuple[int, str, float]] = []
    scheduled: list[tuple[str, str]] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "set_timer", lambda delay, cb: timers.append((delay, cb)))
    monkeypatch.setattr(
        "zeus.dashboard.app.resolve_agent_session_path_with_source",
        lambda _agent: ("/tmp/top-session.jsonl", "env"),
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.os.path.isfile",
        lambda path: path == "/tmp/top-session.jsonl",
    )
    monkeypatch.setattr(
        "zeus.dashboard.app.close_window",
        lambda agent: closed.append(f"{agent.socket}:{agent.kitty_id}"),
    )

    def _popen(cmd, **kwargs):  # noqa: ANN001
        popen_calls.append((list(cmd), dict(kwargs["env"])))
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr("zeus.dashboard.app.subprocess.Popen", _popen)
    monkeypatch.setattr(
        "zeus.dashboard.app.move_pid_to_workspace_and_focus_later",
        lambda pid, ws, delay: moved.append((pid, ws, delay)),
    )
    monkeypatch.setattr(
        app,
        "schedule_polemarch_bootstrap",
        lambda agent_id, requested_name: scheduled.append((agent_id, requested_name)),
    )

    ok = app.do_promote_hippeus_to_polemarch(top)

    assert ok is True
    assert closed == ["/tmp/kitty-1:1"]

    assert popen_calls
    cmd, env = popen_calls[-1]
    assert cmd[:5] == ["kitty", "--directory", "/tmp/project", "--hold", "bash"]
    assert env["ZEUS_AGENT_NAME"] == "top"
    assert env["ZEUS_AGENT_ID"] == "top-1"
    assert env["ZEUS_ROLE"] == "polemarch"
    assert env["ZEUS_SESSION_PATH"] == "/tmp/top-session.jsonl"
    assert env["ZEUS_PHALANX_ID"] == "phalanx-top-1"
    assert "ZEUS_PARENT_ID" not in env

    assert moved == [(1234, "5", 0.5)]
    assert scheduled == [("top-1", "top")]
    assert notices[-1] == "Promoted Hippeus to Polemarch: top"
    assert timers and timers[-1][0] == 1.0


def test_confirm_promote_screen_polemarch_prompt_is_explicit() -> None:
    agent = _agent("planner", kitty_id=1, agent_id="planner-1")
    screen = ConfirmPromoteScreen(agent=agent, promote_to="polemarch")

    assert screen._prompt_text() == "Promote Hippeus [bold]planner[/bold] to Polemarch?"


def test_action_promote_selected_pushes_confirm_for_hoplite_tmux(monkeypatch) -> None:
    app = ZeusApp()
    polemarch = _agent("polemarch", kitty_id=1, agent_id="polemarch-1")
    hoplite = _hoplite_tmux(owner_id="polemarch-1")
    polemarch.tmux_sessions = [hoplite]
    app.agents = [polemarch]

    pushed: list[object] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: hoplite)
    monkeypatch.setattr(app, "push_screen", lambda screen: pushed.append(screen))

    app.action_promote_selected()

    assert pushed
    assert isinstance(pushed[0], ConfirmPromoteScreen)
    assert pushed[0].sess is hoplite


def test_do_promote_hoplite_tmux_retags_session(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = False
    polemarch = _agent("polemarch", kitty_id=1, agent_id="polemarch-1")
    hoplite = _hoplite_tmux(owner_id="polemarch-1")
    polemarch.tmux_sessions = [hoplite]
    app.agents = [polemarch]

    notices: list[str] = []
    polled: list[bool] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))
    monkeypatch.setattr(
        "zeus.dashboard.app.promote_hoplite_to_stygian_hippeus",
        lambda _sess: (True, ""),
    )

    ok = app.do_promote_hoplite_tmux(hoplite)

    assert ok is True
    assert notices[-1] == "Promoted Hoplite to Stygian Hippeus: hoplite-a"
    assert polled == [True]


def test_action_promote_selected_rejects_non_hoplite_tmux_rows(monkeypatch) -> None:
    app = ZeusApp()
    parent = _agent("parent", kitty_id=1, agent_id="parent-1")
    viewer = TmuxSession(
        name="viewer",
        command="",
        cwd="/tmp/project",
        owner_id="",
        role="",
        phalanx_id="",
        agent_id="",
    )
    parent.tmux_sessions = [viewer]
    app.agents = [parent]

    notices: list[str] = []

    monkeypatch.setattr(app, "_should_ignore_table_action", lambda: False)
    monkeypatch.setattr(app, "_get_selected_tmux", lambda: viewer)
    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))

    app.action_promote_selected()

    assert notices[-1] == "Select a Hoplite tmux row to promote"
