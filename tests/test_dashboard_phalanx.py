"""Tests for Polemarch/Hoplite phalanx rendering and classification."""

import inspect

from zeus.dashboard.app import ZeusApp
from zeus.models import AgentWindow, TmuxSession


def _agent(agent_id: str = "agent-1") -> AgentWindow:
    return AgentWindow(
        kitty_id=1,
        socket="/tmp/kitty-1",
        name="polemarch",
        pid=101,
        kitty_pid=201,
        cwd="/tmp/project",
        agent_id=agent_id,
    )


def _tmux(
    *,
    role: str = "",
    owner_id: str = "",
    phalanx_id: str = "",
) -> TmuxSession:
    return TmuxSession(
        name="sess",
        command="pi",
        cwd="/tmp/project",
        role=role,
        owner_id=owner_id,
        phalanx_id=phalanx_id,
    )


def test_is_hoplite_session_for_requires_role_owner_and_phalanx() -> None:
    agent = _agent(agent_id="polemarch-1")

    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ) is True

    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="", owner_id="polemarch-1", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="other", phalanx_id="phalanx-1"),
    ) is False
    assert ZeusApp._is_hoplite_session_for(
        agent,
        _tmux(role="hoplite", owner_id="polemarch-1", phalanx_id=""),
    ) is False


def test_render_agent_table_marks_polemarch_row_and_lists_hoplites() -> None:
    source = inspect.getsource(ZeusApp._render_agent_table_and_status)

    assert "🛡{hoplite_count}" in source
    assert "└ ⚔" in source
    assert "Phalanx (" not in source
    assert "self._is_hoplite_session_for" in source
