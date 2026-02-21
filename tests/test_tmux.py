"""Tests for tmux-to-agent matching."""

from typing import Any
import subprocess

import zeus.tmux as tmux
from zeus.models import AgentWindow, TmuxSession
from zeus.tmux import backfill_tmux_owner_options, match_tmux_to_agents


def _make_agent(
    name: str,
    cwd: str,
    screen_text: str = "",
    agent_id: str = "",
) -> AgentWindow:
    a = AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name=name,
        pid=100,
        kitty_pid=99,
        cwd=cwd,
        agent_id=agent_id,
    )
    a._screen_text = screen_text
    return a


def _make_tmux(
    name: str,
    cwd: str,
    owner_id: str = "",
    env_agent_id: str = "",
    agent_id: str = "",
    agent_id_source: str = "",
) -> TmuxSession:
    return TmuxSession(
        name=name,
        command="bash",
        cwd=cwd,
        owner_id=owner_id,
        env_agent_id=env_agent_id,
        agent_id=agent_id,
        agent_id_source=agent_id_source,
    )


def test_extract_start_command_agent_id_reads_inline_env_assignment() -> None:
    cmd = (
        '"ZEUS_AGENT_ID=hoplite-123 ZEUS_PARENT_ID=polemarch-1 '
        'ZEUS_ROLE=hoplite exec pi"'
    )
    assert tmux._extract_start_command_agent_id(cmd) == "hoplite-123"


def test_extract_start_command_agent_id_returns_empty_when_missing() -> None:
    assert tmux._extract_start_command_agent_id("exec pi") == ""


def test_owner_id_match_takes_priority() -> None:
    owner = _make_agent("owner", "/a", agent_id="agent-1")
    other = _make_agent("other", "/a/b", agent_id="agent-2")
    sess = _make_tmux(
        "build",
        "/nowhere",
        owner_id="agent-1",
        agent_id="agent-2",
        agent_id_source="option",
    )

    match_tmux_to_agents([owner, other], [sess])

    assert len(owner.tmux_sessions) == 1
    assert len(other.tmux_sessions) == 0
    assert owner.tmux_sessions[0].match_source == "owner-id"


def test_option_agent_id_match_when_owner_not_set() -> None:
    owner = _make_agent("owner", "/a", agent_id="agent-1")
    other = _make_agent("other", "/a/b", agent_id="agent-2")
    sess = _make_tmux(
        "build",
        "/nowhere",
        agent_id="agent-2",
        agent_id_source="option",
    )

    match_tmux_to_agents([owner, other], [sess])

    assert len(owner.tmux_sessions) == 0
    assert len(other.tmux_sessions) == 1
    assert other.tmux_sessions[0].match_source == "option-agent-id"


def test_start_command_agent_id_match_when_owner_not_set() -> None:
    owner = _make_agent("owner", "/a", agent_id="agent-1")
    other = _make_agent("other", "/a/b", agent_id="agent-2")
    sess = _make_tmux(
        "build",
        "/nowhere",
        agent_id="agent-2",
        agent_id_source="start-command",
    )

    match_tmux_to_agents([owner, other], [sess])

    assert len(owner.tmux_sessions) == 0
    assert len(other.tmux_sessions) == 1
    assert other.tmux_sessions[0].match_source == "start-command-agent-id"


def test_env_id_match_when_session_agent_id_missing() -> None:
    owner = _make_agent("owner", "/a", agent_id="agent-1")
    other = _make_agent("other", "/a/b", agent_id="agent-2")
    sess = _make_tmux("build", "/nowhere", env_agent_id="agent-2")

    match_tmux_to_agents([owner, other], [sess])

    assert len(owner.tmux_sessions) == 0
    assert len(other.tmux_sessions) == 1
    assert other.tmux_sessions[0].match_source == "env-id"


def test_no_match_without_deterministic_ids() -> None:
    agent = _make_agent("dev", "/home/user/project", screen_text="build")
    sess = _make_tmux("build", "/home/user/project")

    match_tmux_to_agents([agent], [sess])

    assert len(agent.tmux_sessions) == 0


def test_multiple_sessions_match_by_deterministic_ids() -> None:
    a1 = _make_agent("front", "/home/user/frontend", agent_id="agent-1")
    a2 = _make_agent("back", "/home/user/backend", agent_id="agent-2")
    s1 = _make_tmux("fe-build", "/tmp", agent_id="agent-1", agent_id_source="option")
    s2 = _make_tmux("be-test", "/tmp", agent_id="agent-2", agent_id_source="start-command")

    match_tmux_to_agents([a1, a2], [s1, s2])

    assert len(a1.tmux_sessions) == 1
    assert a1.tmux_sessions[0].name == "fe-build"
    assert len(a2.tmux_sessions) == 1
    assert a2.tmux_sessions[0].name == "be-test"


def test_backfill_stamps_owner_for_deterministic_match(monkeypatch) -> None:
    agent = _make_agent("dev", "/home/user/project", agent_id="agent-1")
    sess = _make_tmux("build", "/tmp", agent_id="agent-1", agent_id_source="option")

    match_tmux_to_agents([agent], [sess])

    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux.subprocess, "run", fake_run)

    backfill_tmux_owner_options([agent])

    assert calls
    assert calls[0] == [
        "tmux",
        "set-option",
        "-t",
        "build",
        "@zeus_owner",
        "agent-1",
    ]


def test_backfill_skips_unmatched_session(monkeypatch) -> None:
    agent = _make_agent("dev", "/home/user/project", screen_text="build", agent_id="agent-1")
    sess = _make_tmux("build", "/home/user/project")

    match_tmux_to_agents([agent], [sess])

    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        **_: Any,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux.subprocess, "run", fake_run)

    backfill_tmux_owner_options([agent])

    assert sess.match_source == ""
    assert calls == []
