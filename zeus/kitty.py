"""Kitty remote control, agent discovery, window management."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from glob import glob
import uuid

from .config import AGENT_IDS_FILE, NAMES_FILE
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


def load_agent_ids() -> dict[str, str]:
    """Load persisted agent ids: {"socket:kitty_id": "agent_id"}."""
    try:
        raw = json.loads(AGENT_IDS_FILE.read_text())
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): str(v)
            for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_agent_ids(ids: dict[str, str]) -> None:
    AGENT_IDS_FILE.write_text(json.dumps(ids))


def generate_agent_id() -> str:
    """Generate a stable id for agent ownership mapping."""
    return uuid.uuid4().hex


# Backward-compatible aliases for older imports.
_load_names = load_names
_save_names = save_names
_load_agent_ids = load_agent_ids
_save_agent_ids = save_agent_ids


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
    ids: dict[str, str] = load_agent_ids()
    ids_changed: bool = False
    live_keys: set[str] = set()

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
                    name: str | None = env.get("ZEUS_AGENT_NAME")

                    if not name:
                        if not _looks_like_pi_window(win):
                            continue
                        name = f"pi-{win['id']}"

                    win_id = int(win["id"])
                    key = f"{socket}:{win_id}"
                    live_keys.add(key)
                    env_agent_id = (env.get("ZEUS_AGENT_ID") or "").strip()
                    persisted_id = (ids.get(key) or "").strip()
                    if env_agent_id:
                        agent_id = env_agent_id
                    elif persisted_id:
                        agent_id = persisted_id
                    else:
                        agent_id = generate_agent_id()

                    if ids.get(key) != agent_id:
                        ids[key] = agent_id
                        ids_changed = True

                    agents.append(AgentWindow(
                        kitty_id=win_id,
                        socket=socket,
                        name=name,
                        pid=win.get("pid", 0),
                        kitty_pid=kitty_pid,
                        cwd=win.get("cwd", ""),
                        agent_id=agent_id,
                        parent_id=(env.get("ZEUS_PARENT_ID") or "").strip(),
                        role=(env.get("ZEUS_ROLE") or "").strip().lower(),
                        session_path=env.get("ZEUS_SESSION_PATH", ""),
                    ))

    stale_keys = [k for k in ids if k not in live_keys]
    if stale_keys:
        for key in stale_keys:
            ids.pop(key, None)
        ids_changed = True

    if ids_changed:
        save_agent_ids(ids)

    # Apply name overrides (lineage uses parent_id, so no parent-name rewrites).
    overrides: dict[str, str] = load_names()
    for a in agents:
        agent_key: str = f"{a.socket}:{a.kitty_id}"
        if agent_key in overrides:
            a.name = overrides[agent_key]
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


def resolve_agent_session_path(agent: AgentWindow) -> str | None:
    """Resolve the best-known pi session file for an agent.

    Prefer explicit ZEUS_SESSION_PATH (deterministic per-window), then
    fallback to newest session for the working directory.
    """
    explicit = (agent.session_path or "").strip()
    if explicit:
        return explicit
    return find_current_session(agent.cwd)


def spawn_subagent(
    agent: AgentWindow, name: str, workspace: str = ""
) -> str | None:
    """Fork the agent's session and launch a sub-agent in a new kitty window."""
    cwd: str = agent.cwd
    source: str | None = resolve_agent_session_path(agent)
    if not source or not Path(source).is_file():
        return None
    forked: str | None = fork_session(source, cwd)
    if not forked:
        return None
    parent_id = (agent.agent_id or "").strip()
    if not parent_id:
        return None

    env: dict[str, str] = os.environ.copy()
    env["ZEUS_AGENT_NAME"] = name
    env["ZEUS_PARENT_ID"] = parent_id
    env["ZEUS_AGENT_ID"] = generate_agent_id()
    env["ZEUS_ROLE"] = "hippeus"
    env["ZEUS_SESSION_PATH"] = forked
    proc = subprocess.Popen(
        ["kitty", "--directory", cwd, "--hold",
         "bash", "-lc", f"pi --session {shlex.quote(forked)}"],
        env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if workspace and workspace != "?":
        move_pid_to_workspace_and_focus_later(proc.pid, workspace, delay=0.5)
    return forked
