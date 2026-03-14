"""Kitty remote control, agent discovery, window management."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from glob import glob
from typing import Any
import uuid

from .config import AGENT_IDS_FILE, NAMES_FILE
from .models import AgentWindow
from .sessions import find_current_session, fork_session
from .session_runtime import (
    RuntimeSessionEntry,
    list_runtime_sessions,
    read_adopted_agent_id,
    read_runtime_session_path,
    write_session_adoption,
)
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


_MAX_KITTY_REMOTE_WORKERS = 16
_PI_WORD_RE = re.compile(r"(?:^|\s)pi(?:\s|$)")


def _kitty_remote_worker_count(item_count: int) -> int:
    return max(1, min(_MAX_KITTY_REMOTE_WORKERS, item_count))


def _socket_kitty_pid(socket: str) -> int:
    try:
        return int(socket.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _load_socket_windows(socket: str) -> tuple[str, int, list[dict[str, Any]]]:
    kitty_pid = _socket_kitty_pid(socket)
    raw = kitty_cmd(socket, "ls")
    if not raw:
        return socket, kitty_pid, []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return socket, kitty_pid, []
    if not isinstance(parsed, list):
        return socket, kitty_pid, []
    return socket, kitty_pid, [item for item in parsed if isinstance(item, dict)]


def _list_socket_windows(sockets: list[str]) -> list[tuple[str, int, list[dict[str, Any]]]]:
    ordered_sockets = sorted(sockets)
    if len(ordered_sockets) <= 1:
        return [_load_socket_windows(socket) for socket in ordered_sockets]
    with ThreadPoolExecutor(
        max_workers=_kitty_remote_worker_count(len(ordered_sockets)),
        thread_name_prefix="zeus-kitty-ls",
    ) as executor:
        return list(executor.map(_load_socket_windows, ordered_sockets))


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


def _normalize_session_path(raw: str) -> str:
    expanded = os.path.expanduser(raw.strip())
    if not expanded or not os.path.isabs(expanded):
        return ""
    if not os.path.isfile(expanded):
        return ""
    return expanded


def _extract_pi_session_path(win: dict) -> str:
    tokens = _iter_cmdline_tokens(win.get("cmdline") or [])
    for idx, token in enumerate(tokens):
        candidate = ""
        if token == "--session" and idx + 1 < len(tokens):
            candidate = tokens[idx + 1]
        elif token.startswith("--session="):
            candidate = token.split("=", 1)[1]
        normalized = _normalize_session_path(candidate)
        if normalized:
            return normalized
    return ""


def discover_agents() -> list[AgentWindow]:
    agents: list[AgentWindow] = []
    ids: dict[str, str] = load_agent_ids()
    ids_changed: bool = False
    live_keys: set[str] = set()
    overrides: dict[str, str] = load_names()
    runtime_sessions = list_runtime_sessions()
    runtime_by_path = {entry.session_path: entry for entry in runtime_sessions}
    runtime_by_cwd: dict[str, list[RuntimeSessionEntry]] = defaultdict(list)
    for entry in runtime_sessions:
        runtime_by_cwd[entry.cwd].append(entry)
    used_runtime_session_paths: set[str] = set()

    raw_windows: list[dict[str, Any]] = []

    # Track committed final names to prevent duplicates across kitty instances.
    # Pre-seed with override destination names so auto-naming avoids them.
    committed_names: set[str] = set()
    for override_name in overrides.values():
        committed_names.add(override_name.strip().casefold())

    for socket, kitty_pid, os_windows in _list_socket_windows(discover_sockets()):
        for os_win in os_windows:
            for tab in os_win.get("tabs", []):
                for win in tab.get("windows", []):
                    env: dict[str, str] = win.get("env", {})
                    win_id = int(win["id"])
                    key = f"{socket}:{win_id}"
                    name: str | None = env.get("ZEUS_AGENT_NAME")

                    if not name:
                        if not _looks_like_pi_window(win):
                            continue
                        candidate = f"pi-{win_id}"
                        if key not in overrides and candidate.casefold() in committed_names:
                            n = 1
                            while f"pi-{n}".casefold() in committed_names:
                                n += 1
                            candidate = f"pi-{n}"
                        name = candidate

                    if key not in overrides:
                        committed_names.add(name.strip().casefold())

                    live_keys.add(key)
                    raw_windows.append(
                        {
                            "socket": socket,
                            "kitty_pid": kitty_pid,
                            "win": win,
                            "env": env,
                            "key": key,
                            "name": name,
                            "win_id": win_id,
                            "cwd": str(win.get("cwd", "")).strip(),
                        }
                    )

    def _build_agent(
        item: dict[str, Any],
        *,
        agent_id: str,
        session_path: str,
        bus_capable: bool,
    ) -> AgentWindow:
        env = item["env"]
        assert isinstance(env, dict)
        win = item["win"]
        assert isinstance(win, dict)
        return AgentWindow(
            kitty_id=int(item["win_id"]),
            socket=str(item["socket"]),
            name=str(item["name"]),
            pid=win.get("pid", 0),
            kitty_pid=int(item["kitty_pid"]),
            cwd=str(item["cwd"]),
            agent_id=agent_id,
            parent_id=(env.get("ZEUS_PARENT_ID") or "").strip(),
            role=(env.get("ZEUS_ROLE") or "").strip().lower(),
            session_path=session_path,
            bus_capable=bus_capable,
        )

    unresolved: list[dict[str, Any]] = []

    for item in raw_windows:
        env = item["env"]
        assert isinstance(env, dict)
        key = str(item["key"])
        persisted_id = (ids.get(key) or "").strip()
        env_agent_id = (env.get("ZEUS_AGENT_ID") or "").strip()
        env_session_path = _normalize_session_path(env.get("ZEUS_SESSION_PATH") or "")
        cmd_session_path = _extract_pi_session_path(item["win"])

        agent_id = ""
        session_path = ""
        bus_capable = False

        if env_agent_id:
            agent_id = env_agent_id
            session_path = (
                read_runtime_session_path(agent_id)
                or env_session_path
                or cmd_session_path
            )
            bus_capable = True
        elif persisted_id:
            session_path = read_runtime_session_path(persisted_id) or ""
            if session_path:
                agent_id = persisted_id
                bus_capable = True

        if not agent_id:
            unresolved.append(item)
            continue

        if ids.get(key) != agent_id:
            ids[key] = agent_id
            ids_changed = True

        if session_path:
            used_runtime_session_paths.add(session_path)

        agents.append(
            _build_agent(
                item,
                agent_id=agent_id,
                session_path=session_path,
                bus_capable=bus_capable,
            )
        )

    for item in unresolved:
        env = item["env"]
        assert isinstance(env, dict)
        key = str(item["key"])
        cwd = str(item["cwd"])
        persisted_id = (ids.get(key) or "").strip()
        candidate_id = persisted_id or generate_agent_id()
        env_session_path = _normalize_session_path(env.get("ZEUS_SESSION_PATH") or "")
        cmd_session_path = _extract_pi_session_path(item["win"])

        matched_session_path = ""
        explicit_path = env_session_path or cmd_session_path
        if explicit_path and explicit_path not in used_runtime_session_paths:
            matched_session_path = explicit_path
        else:
            runtime_candidates = [
                entry
                for entry in runtime_by_cwd.get(cwd, [])
                if entry.session_path not in used_runtime_session_paths
            ]
            if len(runtime_candidates) == 1:
                matched_session_path = runtime_candidates[0].session_path

        adopted_agent_id = ""
        bus_capable = False
        if matched_session_path:
            runtime_entry = runtime_by_path.get(matched_session_path)
            adopted_agent_id = read_adopted_agent_id(matched_session_path) or (
                (runtime_entry.agent_id or "").strip() if runtime_entry is not None else ""
            )
            resolved_agent_id = adopted_agent_id or candidate_id
            bus_capable = write_session_adoption(matched_session_path, resolved_agent_id)
            if bus_capable:
                candidate_id = resolved_agent_id
                used_runtime_session_paths.add(matched_session_path)

        session_path = matched_session_path or explicit_path or find_current_session(cwd) or ""
        agent_id = candidate_id

        if ids.get(key) != agent_id:
            ids[key] = agent_id
            ids_changed = True

        agents.append(
            _build_agent(
                item,
                agent_id=agent_id,
                session_path=session_path,
                bus_capable=bus_capable,
            )
        )

    stale_keys = [k for k in ids if k not in live_keys]
    if stale_keys:
        for key in stale_keys:
            ids.pop(key, None)
        ids_changed = True

    if ids_changed:
        save_agent_ids(ids)

    for agent in agents:
        agent_key: str = f"{agent.socket}:{agent.kitty_id}"
        if agent_key in overrides:
            agent.name = overrides[agent_key]
    return agents


def ensure_unique_agent_names(agents: list[AgentWindow]) -> None:
    """Enforce unique display names across all agents.

    CRITICAL INVARIANT: messaging uses display names for routing, so
    duplicates cause mis-delivery.  Colliding names get a numeric suffix.
    Sort by agent_id for deterministic, stable disambiguation across polls.
    """
    groups: dict[str, list[AgentWindow]] = defaultdict(list)
    for agent in agents:
        groups[agent.name.strip().casefold()].append(agent)

    all_used: set[str] = {a.name.strip().casefold() for a in agents}

    for _norm, group in groups.items():
        if len(group) <= 1:
            continue
        group.sort(key=lambda a: a.agent_id or "")
        for agent in group[1:]:
            base = agent.name
            suffix = 2
            while f"{base}-{suffix}".strip().casefold() in all_used:
                suffix += 1
            agent.name = f"{base}-{suffix}"
            all_used.add(agent.name.strip().casefold())


def _screen_text_args(
    agent: AgentWindow,
    *,
    full: bool = False,
    ansi: bool = False,
) -> list[str]:
    args = ["get-text", "--match", f"id:{agent.kitty_id}"]
    if full:
        args.extend(["--extent", "all"])
    if ansi:
        args.append("--ansi")
    return args


def _fetch_agent_screen_text(
    item: tuple[str, str, list[str]],
) -> tuple[str, str]:
    key, socket, args = item
    text = kitty_cmd(socket, *args)
    return key, (text or "")


def get_screen_texts(
    agents: list[AgentWindow],
    *,
    full: bool = False,
    ansi: bool = False,
) -> dict[str, str]:
    tasks = [
        (
            f"{agent.socket}:{agent.kitty_id}",
            agent.socket,
            _screen_text_args(agent, full=full, ansi=ansi),
        )
        for agent in agents
    ]
    if not tasks:
        return {}
    if len(tasks) == 1:
        key, socket, args = tasks[0]
        return {key: (kitty_cmd(socket, *args) or "")}
    with ThreadPoolExecutor(
        max_workers=_kitty_remote_worker_count(len(tasks)),
        thread_name_prefix="zeus-kitty-text",
    ) as executor:
        return dict(executor.map(_fetch_agent_screen_text, tasks))


def get_screen_text(
    agent: AgentWindow, full: bool = False, ansi: bool = False,
) -> str:
    text: str | None = kitty_cmd(
        agent.socket,
        *_screen_text_args(agent, full=full, ansi=ansi),
    )
    return text or ""


def focus_window(agent: AgentWindow) -> None:
    focus_pid(agent.kitty_pid)


def close_window(agent: AgentWindow) -> None:
    kitty_cmd(agent.socket, "close-window", "--match", f"id:{agent.kitty_id}")


def resolve_agent_session_path_with_source(agent: AgentWindow) -> tuple[str | None, str]:
    """Resolve session path with provenance for reliability decisions.

    Returns ``(path, source)`` where source is one of:
      - ``runtime``: runtime sync from Zeus pi extension
      - ``env``: launch-time ZEUS_SESSION_PATH
      - ``cwd``: newest session in agent cwd (heuristic fallback)
      - ``none``: no candidate found

    If ZEUS_SESSION_PATH is present but points to a missing file, we treat it as
    stale and attempt cwd fallback. The caller still decides whether cwd fallback
    is safe (e.g. shared cwd ambiguity).
    """
    runtime_path = read_runtime_session_path(agent.agent_id)
    if runtime_path:
        return runtime_path, "runtime"

    explicit = (agent.session_path or "").strip()
    if explicit:
        if os.path.isfile(explicit):
            return explicit, "env"
        fallback = find_current_session(agent.cwd)
        if fallback and fallback != explicit:
            return fallback, "cwd"
        return explicit, "env"

    fallback = find_current_session(agent.cwd)
    if fallback:
        return fallback, "cwd"
    return None, "none"


def resolve_agent_session_path(agent: AgentWindow) -> str | None:
    """Resolve the best-known pi session file for an agent."""
    path, _source = resolve_agent_session_path_with_source(agent)
    return path


def spawn_subagent(
    agent: AgentWindow,
    name: str,
    workspace: str = "",
    *,
    model_spec: str = "",
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

    clean_model = (model_spec or "").strip()

    env: dict[str, str] = os.environ.copy()
    env["ZEUS_AGENT_NAME"] = name
    env["ZEUS_PARENT_ID"] = parent_id
    env["ZEUS_AGENT_ID"] = generate_agent_id()
    env["ZEUS_ROLE"] = "hippeus"
    env["ZEUS_SESSION_PATH"] = forked

    pi_cmd = f"pi --session {shlex.quote(forked)}"
    if clean_model:
        pi_cmd += f" --model {shlex.quote(clean_model)}"

    proc = subprocess.Popen(
        ["kitty", "--directory", cwd, "--hold", "zsh", "-ilc", f"exec {pi_cmd}"],
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if workspace and workspace != "?":
        move_pid_to_workspace_and_focus_later(proc.pid, workspace, delay=0.5)
    return forked
