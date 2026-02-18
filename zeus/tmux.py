"""Tmux session discovery and agent matching."""

from __future__ import annotations

import re
import subprocess

from .models import AgentWindow, TmuxSession


def _run_tmux(command: list[str], timeout: float = 3) -> subprocess.CompletedProcess[str] | None:
    """Run a tmux command and return the completed process or None on hard failure."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def ensure_tmux_update_environment(var_name: str = "ZEUS_AGENT_ID") -> None:
    """Ensure tmux server propagates ZEUS_AGENT_ID to newly-created sessions."""
    r = _run_tmux(["tmux", "show", "-gv", "update-environment"], timeout=2)
    if r is None or r.returncode != 0:
        return
    # tmux returns space-separated values (possibly across lines)
    raw = r.stdout.strip()
    current: set[str] = set()
    for chunk in raw.replace("\n", " ").split():
        stripped = chunk.strip()
        if stripped:
            current.add(stripped)

    if var_name in current:
        # Clean up duplicates if present (from earlier buggy appends)
        count = raw.split().count(var_name)
        if count > 1:
            _deduplicate_update_environment(current)
        return
    _run_tmux(["tmux", "set", "-ga", "update-environment", var_name], timeout=2)


def _deduplicate_update_environment(entries: set[str]) -> None:
    """Rewrite update-environment with deduplicated entries."""
    # Reset to default then re-add each unique entry
    _run_tmux(
        ["tmux", "set", "-g", "update-environment",
         " ".join(sorted(entries))],
        timeout=2,
    )


def _read_tmux_option(session_name: str, option_name: str) -> str:
    """Read a tmux session option value, returning empty string when missing."""
    r = _run_tmux(
        ["tmux", "show-options", "-t", session_name, "-qv", option_name],
        timeout=2,
    )
    if r is None or r.returncode != 0:
        return ""
    return r.stdout.strip()


def _read_tmux_owner_id(session_name: str) -> str:
    """Read session option @zeus_owner, if present."""
    return _read_tmux_option(session_name, "@zeus_owner")


def _read_tmux_role(session_name: str) -> str:
    """Read session option @zeus_role, if present."""
    return _read_tmux_option(session_name, "@zeus_role")


def _read_tmux_phalanx(session_name: str) -> str:
    """Read session option @zeus_phalanx, if present."""
    return _read_tmux_option(session_name, "@zeus_phalanx")


def _read_tmux_agent_id(session_name: str) -> str:
    """Read session option @zeus_agent, if present."""
    return _read_tmux_option(session_name, "@zeus_agent")


def _read_tmux_backend(session_name: str) -> str:
    """Read session option @zeus_backend, if present."""
    return _read_tmux_option(session_name, "@zeus_backend")


def _read_tmux_display_name(session_name: str) -> str:
    """Read session option @zeus_name, if present."""
    return _read_tmux_option(session_name, "@zeus_name")


def _read_tmux_session_path(session_name: str) -> str:
    """Read session option @zeus_session_path, if present."""
    return _read_tmux_option(session_name, "@zeus_session_path")


def _extract_start_command_agent_id(command: str) -> str:
    """Extract ZEUS_AGENT_ID from pane_start_command when present.

    We prefer this over tmux session environment because update-environment can
    cause ZEUS_AGENT_ID in tmux env to reflect the creator/owner rather than the
    process running in the pane.
    """
    cmd = command.strip().strip('"').strip("'")
    if not cmd:
        return ""
    match = re.search(r"(?:^|\s)ZEUS_AGENT_ID=([A-Za-z0-9_-]+)(?:\s|$)", cmd)
    if not match:
        return ""
    return match.group(1).strip()


def _read_tmux_env_agent_id(session_name: str) -> str:
    """Read ZEUS_AGENT_ID from a tmux session environment, if present."""
    r = _run_tmux(
        ["tmux", "show-environment", "-t", session_name, "ZEUS_AGENT_ID"],
        timeout=2,
    )
    if r is None or r.returncode != 0:
        return ""
    line = r.stdout.strip()
    if not line or "=" not in line:
        return ""
    key, value = line.split("=", 1)
    if key != "ZEUS_AGENT_ID":
        return ""
    return value.strip()


def _stamp_tmux_owner(session_name: str, owner_id: str) -> bool:
    """Persist deterministic ownership on a tmux session."""
    if not owner_id.strip():
        return False
    r = _run_tmux(
        ["tmux", "set-option", "-t", session_name, "@zeus_owner", owner_id],
        timeout=2,
    )
    return r is not None and r.returncode == 0


def discover_tmux_sessions() -> list[TmuxSession]:
    """Get all tmux sessions with pane info and Zeus ownership metadata."""
    r = _run_tmux(
        ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}\t#{session_created}"],
        timeout=3,
    )
    if r is None or r.returncode != 0:
        return []

    sessions: list[TmuxSession] = []
    for line in r.stdout.strip().splitlines():
        parts: list[str] = line.split("\t")
        if len(parts) < 3:
            continue
        name, attached, created = parts[0], parts[1], parts[2]
        is_attached: bool = attached != "0"

        cmd_str: str = ""
        cwd: str = ""
        pane_pid: int = 0
        p = _run_tmux(
            [
                "tmux",
                "list-panes",
                "-t",
                name,
                "-F",
                "#{pane_start_command}\t#{pane_current_path}\t#{pane_pid}",
            ],
            timeout=3,
        )
        if p is not None and p.returncode == 0 and p.stdout.strip():
            pinfo: list[str] = p.stdout.strip().splitlines()[0].split("\t")
            cmd_str = pinfo[0] if len(pinfo) > 0 else ""
            cwd = pinfo[1] if len(pinfo) > 1 else ""
            if len(pinfo) > 2 and pinfo[2].isdigit():
                pane_pid = int(pinfo[2])

        owner_id = _read_tmux_owner_id(name)
        env_agent_id = _read_tmux_env_agent_id(name)
        role = _read_tmux_role(name)
        phalanx_id = _read_tmux_phalanx(name)
        backend = _read_tmux_backend(name)
        display_name = _read_tmux_display_name(name)
        session_path = _read_tmux_session_path(name)
        option_agent_id = _read_tmux_agent_id(name).strip()
        start_cmd_agent_id = _extract_start_command_agent_id(cmd_str).strip()
        env_agent_id = env_agent_id.strip()

        session_agent_id = ""
        session_agent_id_source = ""
        if option_agent_id:
            session_agent_id = option_agent_id
            session_agent_id_source = "option"
        elif start_cmd_agent_id:
            session_agent_id = start_cmd_agent_id
            session_agent_id_source = "start-command"
        elif env_agent_id:
            session_agent_id = env_agent_id
            session_agent_id_source = "env"

        sessions.append(
            TmuxSession(
                name=name,
                command=cmd_str,
                cwd=cwd,
                created=int(created) if created.isdigit() else 0,
                attached=is_attached,
                pane_pid=pane_pid,
                owner_id=owner_id,
                env_agent_id=env_agent_id,
                agent_id=session_agent_id,
                agent_id_source=session_agent_id_source,
                role=role,
                phalanx_id=phalanx_id,
                backend=backend,
                display_name=display_name,
                session_path=session_path,
            )
        )
    return sessions


def match_tmux_to_agents(
    agents: list[AgentWindow],
    tmux_sessions: list[TmuxSession],
) -> None:
    """Match tmux sessions to agents.

    Priority:
      1. @zeus_owner option id → unique agent id match.
      2. ZEUS_AGENT_ID from tmux session env → unique agent id match.
      3. screen text — if exactly one agent's screen mentions this specific
         tmux session name, assign it there.
      4. cwd match — tmux session cwd starts with (or equals) agent cwd.
         Pick the agent with the longest matching cwd. Among ties, prefer
         the agent whose screen text mentions this session name.
      5. screen text fallback — first agent whose screen mentions the name.
    """
    agents_by_id: dict[str, list[AgentWindow]] = {}
    for agent in agents:
        if agent.agent_id:
            agents_by_id.setdefault(agent.agent_id, []).append(agent)

    for sess in tmux_sessions:
        sess.match_source = ""

        if sess.owner_id:
            candidates = agents_by_id.get(sess.owner_id, [])
            if len(candidates) == 1:
                candidates[0].tmux_sessions.append(sess)
                sess.match_source = "owner-id"
                continue

        if sess.env_agent_id:
            candidates = agents_by_id.get(sess.env_agent_id, [])
            if len(candidates) == 1:
                candidates[0].tmux_sessions.append(sess)
                sess.match_source = "env-id"
                continue

        # 3. Exact screen-text match on this session's name
        screen_matches: list[AgentWindow] = [
            a for a in agents if sess.name in a._screen_text
        ]
        if len(screen_matches) == 1:
            screen_matches[0].tmux_sessions.append(sess)
            sess.match_source = "screen-exact"
            continue

        # 4. cwd match (most specific wins, screen-text breaks ties)
        best_len: int = -1
        cwd_candidates: list[AgentWindow] = []
        if sess.cwd:
            for agent in agents:
                if agent.cwd and sess.cwd.startswith(agent.cwd):
                    if len(agent.cwd) > best_len:
                        best_len = len(agent.cwd)
                        cwd_candidates = [agent]
                    elif len(agent.cwd) == best_len:
                        cwd_candidates.append(agent)
        if cwd_candidates:
            # Among tied cwd candidates, prefer the one with screen mention
            if len(cwd_candidates) > 1:
                with_screen = [
                    a for a in cwd_candidates
                    if sess.name in a._screen_text
                ]
                if len(with_screen) == 1:
                    cwd_candidates = with_screen
            cwd_candidates[0].tmux_sessions.append(sess)
            sess.match_source = "cwd"
            continue

        # 5. Fall back to first screen text match
        if screen_matches:
            screen_matches[0].tmux_sessions.append(sess)
            sess.match_source = "screen-fallback"
            continue


def backfill_tmux_owner_options(agents: list[AgentWindow]) -> None:
    """Stamp @zeus_owner for matched sessions that are currently unstamped.

    We stamp only high-confidence matches to avoid persisting low-confidence
    associations.
    """
    high_confidence_sources: set[str] = {"env-id", "screen-exact", "cwd"}

    for agent in agents:
        if not agent.agent_id:
            continue
        for sess in agent.tmux_sessions:
            if sess.owner_id:
                continue
            if sess.match_source not in high_confidence_sources:
                continue
            if _stamp_tmux_owner(sess.name, agent.agent_id):
                sess.owner_id = agent.agent_id
