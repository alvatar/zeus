"""Tests for tmux-to-agent matching."""

from zeus.models import AgentWindow, TmuxSession, State
from zeus.tmux import match_tmux_to_agents


def _make_agent(name: str, cwd: str, screen_text: str = "") -> AgentWindow:
    a = AgentWindow(
        kitty_id=1, socket="/tmp/kitty-1", name=name,
        pid=100, kitty_pid=99, cwd=cwd,
    )
    a._screen_text = screen_text
    return a


def _make_tmux(name: str, cwd: str) -> TmuxSession:
    return TmuxSession(name=name, command="bash", cwd=cwd)


def test_cwd_match_exact():
    agent = _make_agent("dev", "/home/user/project")
    sess = _make_tmux("build", "/home/user/project")
    match_tmux_to_agents([agent], [sess])
    assert len(agent.tmux_sessions) == 1
    assert agent.tmux_sessions[0].name == "build"


def test_cwd_match_subdirectory():
    agent = _make_agent("dev", "/home/user/project")
    sess = _make_tmux("test", "/home/user/project/src")
    match_tmux_to_agents([agent], [sess])
    assert len(agent.tmux_sessions) == 1


def test_cwd_most_specific_wins():
    parent = _make_agent("parent", "/home/user")
    child = _make_agent("child", "/home/user/project")
    sess = _make_tmux("build", "/home/user/project/src")
    match_tmux_to_agents([parent, child], [sess])
    assert len(parent.tmux_sessions) == 0
    assert len(child.tmux_sessions) == 1


def test_screen_text_fallback():
    agent = _make_agent("dev", "/other/path", screen_text="running build session")
    sess = _make_tmux("build", "/unrelated/dir")
    match_tmux_to_agents([agent], [sess])
    assert len(agent.tmux_sessions) == 1


def test_no_match():
    agent = _make_agent("dev", "/home/user/project")
    sess = _make_tmux("random", "/totally/different")
    match_tmux_to_agents([agent], [sess])
    assert len(agent.tmux_sessions) == 0


def test_multiple_sessions():
    a1 = _make_agent("front", "/home/user/frontend")
    a2 = _make_agent("back", "/home/user/backend")
    s1 = _make_tmux("fe-build", "/home/user/frontend")
    s2 = _make_tmux("be-test", "/home/user/backend/tests")
    match_tmux_to_agents([a1, a2], [s1, s2])
    assert len(a1.tmux_sessions) == 1
    assert a1.tmux_sessions[0].name == "fe-build"
    assert len(a2.tmux_sessions) == 1
    assert a2.tmux_sessions[0].name == "be-test"
