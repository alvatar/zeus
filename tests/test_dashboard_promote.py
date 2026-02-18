"""Tests for Ctrl+P promotion flow in dashboard actions."""

from zeus.dashboard.app import ZeusApp
from zeus.dashboard.screens import ConfirmPromoteScreen
from zeus.models import AgentWindow, TmuxSession


def _agent(
    name: str,
    *,
    kitty_id: int,
    agent_id: str,
    parent_id: str = "",
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


def test_do_promote_sub_hippeus_persists_override(monkeypatch) -> None:
    app = ZeusApp()
    app._interact_visible = False
    child = _agent(
        "child",
        kitty_id=2,
        agent_id="child-1",
        parent_id="parent-1",
    )

    notices: list[str] = []
    saved: list[set[str]] = []
    polled: list[bool] = []

    monkeypatch.setattr(app, "notify", lambda msg, timeout=3: notices.append(msg))
    monkeypatch.setattr(
        app,
        "_save_promoted_sub_hippeis",
        lambda: saved.append(set(app._promoted_sub_hippeis)),
    )
    monkeypatch.setattr(app, "poll_and_update", lambda: polled.append(True))

    ok = app.do_promote_sub_hippeus(child)

    assert ok is True
    assert app._promoted_sub_hippeis == {"child-1"}
    assert saved[-1] == {"child-1"}
    assert notices[-1] == "Promoted sub-Hippeus to Hippeus: child"
    assert polled == [True]


def test_effective_parent_id_ignores_promoted_sub_hippeus() -> None:
    app = ZeusApp()
    child = _agent(
        "child",
        kitty_id=2,
        agent_id="child-1",
        parent_id="parent-1",
    )

    assert app._effective_parent_id(child) == "parent-1"

    app._promoted_sub_hippeis = {"child-1"}

    assert app._effective_parent_id(child) == ""


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
        "zeus.dashboard.app.promote_hoplite_to_hidden_hippeus",
        lambda _sess: (True, ""),
    )

    ok = app.do_promote_hoplite_tmux(hoplite)

    assert ok is True
    assert notices[-1] == "Promoted Hoplite to Hidden Hippeus: hoplite-a"
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
