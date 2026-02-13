"""Tmux session discovery and agent matching."""

from __future__ import annotations

import subprocess

from .models import AgentWindow, TmuxSession


def discover_tmux_sessions() -> list[TmuxSession]:
    """Get all tmux sessions with pane info."""
    try:
        r = subprocess.run(
            ["tmux", "list-sessions", "-F",
             "#{session_name}\t#{session_attached}\t#{session_created}"],
            capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
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
        try:
            p = subprocess.run(
                ["tmux", "list-panes", "-t", name, "-F",
                 "#{pane_start_command}\t#{pane_current_path}\t#{pane_pid}"],
                capture_output=True, text=True, timeout=3)
            if p.returncode == 0 and p.stdout.strip():
                pinfo: list[str] = p.stdout.strip().splitlines()[0].split("\t")
                cmd_str = pinfo[0] if len(pinfo) > 0 else ""
                cwd = pinfo[1] if len(pinfo) > 1 else ""
                if len(pinfo) > 2 and pinfo[2].isdigit():
                    pane_pid = int(pinfo[2])
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        sessions.append(TmuxSession(
            name=name,
            command=cmd_str,
            cwd=cwd,
            created=int(created) if created.isdigit() else 0,
            attached=is_attached,
            pane_pid=pane_pid,
        ))
    return sessions


def match_tmux_to_agents(
    agents: list[AgentWindow],
    tmux_sessions: list[TmuxSession],
) -> None:
    """Match tmux sessions to agents.

    Priority:
      1. screen text — if exactly one agent's screen mentions this specific
         tmux session name, assign it there (strongest ownership signal).
      2. cwd match — tmux session cwd starts with (or equals) agent cwd.
         Pick the agent with the longest matching cwd.  Among ties, prefer
         the agent whose screen text mentions this session name.
      3. screen text fallback — first agent whose screen mentions the name.
    """
    for sess in tmux_sessions:
        # 1. Exact screen-text match on this session's name
        screen_matches: list[AgentWindow] = [
            a for a in agents if sess.name in a._screen_text
        ]
        if len(screen_matches) == 1:
            screen_matches[0].tmux_sessions.append(sess)
            continue

        # 2. cwd match (most specific wins, screen-text breaks ties)
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
            continue

        # 3. Fall back to first screen text match
        if screen_matches:
            screen_matches[0].tmux_sessions.append(sess)
            continue
