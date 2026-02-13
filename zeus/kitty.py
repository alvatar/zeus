"""Kitty remote control, agent discovery, window management."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from glob import glob

from .config import NAMES_FILE
from .models import AgentWindow
from .sessions import find_current_session, fork_session
from .windowing import focus_pid, move_pid_to_workspace_and_focus_later


def kitty_cmd(
    socket: str, *args: str, timeout: float = 3,
) -> str | None:
    cmd: list[str] = ["kitty", "@", "--to", f"unix:{socket}"] + list(args)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0:
            return r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def load_names() -> dict[str, str]:
    """Load rename overrides: {original_name: new_name}."""
    try:
        return json.loads(NAMES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_names(names: dict[str, str]) -> None:
    NAMES_FILE.write_text(json.dumps(names))


# Backward-compatible aliases for older imports.
_load_names = load_names
_save_names = save_names


def discover_sockets() -> list[str]:
    return glob("/tmp/kitty-*")


_PI_WORD_RE = re.compile(r"(?:^|\s)pi(?:\s|$)")


def _iter_cmdline_tokens(cmdline: list[object]) -> list[str]:
    """Tokenize kitty cmdline entries, including shell '-c' payloads."""
    tokens: list[str] = []
    for part in cmdline:
        text = str(part).strip()
        if not text:
            continue
        try:
            tokens.extend(shlex.split(text))
        except ValueError:
            tokens.extend(text.split())
    return tokens


def _looks_like_pi_window(win: dict) -> bool:
    """Heuristic to detect real pi windows without matching generic shells."""
    cmdline: list[object] = win.get("cmdline") or []
    tokens = _iter_cmdline_tokens(cmdline)
    for tok in tokens:
        base = tok.rsplit("/", 1)[-1]
        if base == "pi":
            return True

    # Fallback: word-boundary match in raw cmdline payloads.
    cmd_str = " ".join(str(x) for x in cmdline).lower()
    if _PI_WORD_RE.search(cmd_str):
        return True

    # pi windows typically have a title starting with π.
    title: str = (win.get("title") or "").strip()
    return title.startswith("π")


def discover_agents() -> list[AgentWindow]:
    agents: list[AgentWindow] = []
    for socket in discover_sockets():
        try:
            kitty_pid = int(socket.rsplit("-", 1)[1])
        except (IndexError, ValueError):
            kitty_pid = 0
        raw: str | None = kitty_cmd(socket, "ls")
        if not raw:
            continue
        try:
            os_windows: list[dict] = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for os_win in os_windows:
            for tab in os_win.get("tabs", []):
                for win in tab.get("windows", []):
                    env: dict[str, str] = win.get("env", {})
                    name: str | None = env.get("AGENTMON_NAME")

                    if not name:
                        if not _looks_like_pi_window(win):
                            continue
                        name = f"pi-{win['id']}"

                    agents.append(AgentWindow(
                        kitty_id=win["id"],
                        socket=socket,
                        name=name,
                        pid=win.get("pid", 0),
                        kitty_pid=kitty_pid,
                        cwd=win.get("cwd", ""),
                        parent_name=env.get("ZEUS_PARENT", ""),
                    ))

    # Apply name overrides and fix parent refs
    overrides: dict[str, str] = load_names()
    orig_to_new: dict[str, str] = {}
    for a in agents:
        key: str = f"{a.socket}:{a.kitty_id}"
        if key in overrides:
            orig_to_new[a.name] = overrides[key]
            a.name = overrides[key]
    for a in agents:
        if a.parent_name and a.parent_name in orig_to_new:
            a.parent_name = orig_to_new[a.parent_name]
    return agents


def get_screen_text(
    agent: AgentWindow, full: bool = False, ansi: bool = False,
) -> str:
    args = ["get-text", "--match", f"id:{agent.kitty_id}"]
    if full:
        args.extend(["--extent", "all"])
    if ansi:
        args.append("--ansi")
    text: str | None = kitty_cmd(agent.socket, *args)
    return text or ""


def focus_window(agent: AgentWindow) -> None:
    focus_pid(agent.kitty_pid)


def close_window(agent: AgentWindow) -> None:
    kitty_cmd(agent.socket, "close-window", "--match", f"id:{agent.kitty_id}")


def spawn_subagent(
    agent: AgentWindow, name: str, workspace: str = ""
) -> str | None:
    """Fork the agent's session and launch a sub-agent in a new kitty window."""
    cwd: str = agent.cwd
    source: str | None = find_current_session(cwd)
    if not source:
        return None
    forked: str | None = fork_session(source, cwd)
    if not forked:
        return None
    env: dict[str, str] = os.environ.copy()
    env["AGENTMON_NAME"] = name
    env["ZEUS_PARENT"] = agent.name
    proc = subprocess.Popen(
        ["kitty", "--directory", cwd, "--hold",
         "bash", "-lc", f"pi --session {forked}"],
        env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if workspace and workspace != "?":
        move_pid_to_workspace_and_focus_later(proc.pid, workspace, delay=0.5)
    return forked
