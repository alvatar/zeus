"""Kitty remote control, agent discovery, window management."""

from __future__ import annotations

import json
import os
import subprocess
import time
import threading
from glob import glob
from pathlib import Path

from .config import NAMES_FILE
from .models import AgentWindow
from .sessions import find_current_session, fork_session


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


def _load_names() -> dict[str, str]:
    """Load rename overrides: {original_name: new_name}."""
    try:
        return json.loads(NAMES_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_names(names: dict[str, str]) -> None:
    NAMES_FILE.write_text(json.dumps(names))


def discover_sockets() -> list[str]:
    return glob("/tmp/kitty-*")


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
                        cmdline: list = win.get("cmdline") or []
                        title: str = (win.get("title") or "").lower()
                        cmd_str: str = " ".join(
                            str(x) for x in cmdline
                        ).lower()
                        looks_like_pi: bool = (
                            " pi" in f" {cmd_str} "
                            or " pi" in title
                            or title.startswith("π")
                        )
                        if not looks_like_pi:
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
    overrides: dict[str, str] = _load_names()
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
    subprocess.run(
        ["swaymsg", f"[pid={agent.kitty_pid}]", "focus"],
        capture_output=True, timeout=3)


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
        def _move_and_focus() -> None:
            time.sleep(0.5)
            try:
                subprocess.run(
                    ["swaymsg", f"[pid={proc.pid}]",
                     "move", "workspace", workspace],
                    capture_output=True, timeout=3)
                subprocess.run(
                    ["swaymsg", "workspace", workspace],
                    capture_output=True, timeout=3)
                subprocess.run(
                    ["swaymsg", f"[pid={proc.pid}]", "focus"],
                    capture_output=True, timeout=3)
            except Exception:
                pass
        threading.Thread(target=_move_and_focus, daemon=True).start()
    return forked
