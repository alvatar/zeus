"""Tmux session discovery and agent matching."""

import subprocess
from typing import Optional

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

    sessions = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, attached, created = parts[0], parts[1], parts[2]
        is_attached = attached != "0"

        cmd_str, cwd = "", ""
        try:
            p = subprocess.run(
                ["tmux", "list-panes", "-t", name, "-F",
                 "#{pane_start_command}\t#{pane_current_path}"],
                capture_output=True, text=True, timeout=3)
            if p.returncode == 0 and p.stdout.strip():
                pinfo = p.stdout.strip().splitlines()[0].split("\t")
                cmd_str = pinfo[0] if len(pinfo) > 0 else ""
                cwd = pinfo[1] if len(pinfo) > 1 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        sessions.append(TmuxSession(
            name=name,
            command=cmd_str,
            cwd=cwd,
            created=int(created) if created.isdigit() else 0,
            attached=is_attached,
        ))
    return sessions


def match_tmux_to_agents(
    agents: list[AgentWindow],
    tmux_sessions: list[TmuxSession],
):
    """Match tmux sessions to agents.

    Priority:
      1. cwd match — tmux session cwd starts with (or equals) agent cwd.
         Pick the agent with the longest matching cwd (most specific).
      2. screen text — tmux session name appears in agent screen text.
    """
    for sess in tmux_sessions:
        # 1. Try cwd match (most specific wins)
        best_agent: Optional[AgentWindow] = None
        best_len = -1
        if sess.cwd:
            for agent in agents:
                if (agent.cwd
                        and sess.cwd.startswith(agent.cwd)
                        and len(agent.cwd) > best_len):
                    best_agent = agent
                    best_len = len(agent.cwd)
        if best_agent:
            best_agent.tmux_sessions.append(sess)
            continue

        # 2. Fall back to screen text match
        for agent in agents:
            if sess.name in agent._screen_text:
                agent.tmux_sessions.append(sess)
                break
