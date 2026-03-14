"""Snapshot save/restore helpers for Zeus dashboard state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
from typing import Any

from .config import STATE_DIR
from .kitty import close_window, discover_agents, resolve_agent_session_path_with_source
from .models import AgentWindow, State, TmuxSession
from .session_runtime import read_runtime_session_path
from .stygian_hippeus import (
    STYGIAN_AGENT_BACKEND,
    STYGIAN_TMUX_BACKEND_TAG,
    resolve_stygian_session_path,
)
from .tmux import discover_tmux_sessions
from .windowing import move_pid_to_workspace_and_focus_later

SNAPSHOTS_DIR = STATE_DIR / "snapshots"
SNAPSHOT_SCHEMA_VERSION = 1


@dataclass
class SaveSnapshotResult:
    ok: bool
    path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entry_count: int = 0
    working_count: int = 0
    closed_count: int = 0


@dataclass
class RestoreSnapshotResult:
    ok: bool
    path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    restored_count: int = 0
    skipped_count: int = 0
    working_total: int = 0
    working_restored: int = 0
    working_skipped: int = 0


def default_snapshot_name() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("snapshot-%Y%m%d-%H%M%S")


def list_snapshot_files() -> list[Path]:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    files = [path for path in SNAPSHOTS_DIR.glob("*.json") if path.is_file()]
    return sorted(files, key=lambda path: path.name, reverse=True)


def save_snapshot_from_dashboard(
    *,
    name: str,
    agents: list[AgentWindow],
    close_all: bool,
) -> SaveSnapshotResult:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []

    for agent in agents:
        if _is_stygian_agent(agent):
            entry, error = _snapshot_entry_for_stygian_agent(agent)
        else:
            entry, error = _snapshot_entry_for_kitty_agent(agent, agents)
        if error:
            errors.append(error)
            continue
        entries.append(entry)

    seen_hoplite_sessions: set[str] = set()
    for parent in agents:
        for sess in parent.tmux_sessions:
            if not _is_hoplite_session_for(parent, sess):
                continue
            if sess.name in seen_hoplite_sessions:
                continue
            seen_hoplite_sessions.add(sess.name)
            entry, error = _snapshot_entry_for_hoplite_session(sess)
            if error:
                errors.append(error)
                continue
            entries.append(entry)

    if not entries and not errors:
        errors.append("No restorable agents found for snapshot")

    if errors:
        return SaveSnapshotResult(ok=False, errors=errors, entry_count=len(entries))

    working_ids = sorted(
        {
            (agent.agent_id or "").strip()
            for agent in agents
            if agent.state == State.WORKING and (agent.agent_id or "").strip()
        }
    )

    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "working_agent_ids": working_ids,
        "entry_count": len(entries),
        "entries": entries,
    }

    snapshot_file = _snapshot_file_path(name)
    snapshot_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    closed_count = 0
    if close_all:
        closed_count, warnings = _close_snapshot_entries(entries, agents)

    return SaveSnapshotResult(
        ok=True,
        path=str(snapshot_file),
        warnings=warnings,
        entry_count=len(entries),
        working_count=len(working_ids),
        closed_count=closed_count,
    )


def restore_snapshot(
    *,
    snapshot_path: str,
    workspace_mode: str,
    if_running: str,
) -> RestoreSnapshotResult:
    payload, load_error = _load_snapshot(Path(snapshot_path))
    if load_error:
        return RestoreSnapshotResult(ok=False, errors=[load_error], path=snapshot_path)

    assert payload is not None
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return RestoreSnapshotResult(
            ok=False,
            errors=["Snapshot payload is malformed: entries must be a list"],
            path=snapshot_path,
        )

    entries: list[dict[str, Any]] = [entry for entry in entries_raw if isinstance(entry, dict)]
    working_ids: set[str] = {
        str(raw).strip()
        for raw in payload.get("working_agent_ids", [])
        if isinstance(raw, str) and str(raw).strip()
    }

    if workspace_mode not in {"original", "current"}:
        return RestoreSnapshotResult(
            ok=False,
            errors=[f"Invalid workspace mode: {workspace_mode}"],
            path=snapshot_path,
            working_total=len(working_ids),
        )
    if if_running not in {"error", "skip", "replace"}:
        return RestoreSnapshotResult(
            ok=False,
            errors=[f"Invalid if-running policy: {if_running}"],
            path=snapshot_path,
            working_total=len(working_ids),
        )

    live_agents = discover_agents()
    live_tmux = discover_tmux_sessions()

    live_agent_ids: set[str] = {
        (agent.agent_id or "").strip() for agent in live_agents if (agent.agent_id or "").strip()
    }
    live_tmux_agent_ids: set[str] = set()
    for sess in live_tmux:
        sess_agent_id = _tmux_agent_id_for_restore(sess)
        if sess_agent_id:
            live_tmux_agent_ids.add(sess_agent_id)
    live_ids = live_agent_ids | live_tmux_agent_ids
    live_tmux_names: set[str] = {sess.name for sess in live_tmux if sess.name}

    snapshot_ids: set[str] = {
        str(entry.get("agent_id", "")).strip() for entry in entries if str(entry.get("agent_id", "")).strip()
    }
    conflicts = sorted(snapshot_ids & live_ids)

    if conflicts and if_running == "error":
        return RestoreSnapshotResult(
            ok=False,
            errors=[
                "Refusing to restore while agent ids are already running: "
                + ", ".join(conflicts)
            ],
            path=snapshot_path,
            working_total=len(working_ids),
        )

    warnings: list[str] = []
    replaced_ids: set[str] = set()

    restored_count = 0
    skipped_count = 0
    errors: list[str] = []
    working_restored = 0
    working_skipped = 0

    for entry in entries:
        kind = str(entry.get("kind", "")).strip().lower()
        agent_id = str(entry.get("agent_id", "")).strip()

        if agent_id and agent_id in live_ids:
            if if_running == "skip":
                skipped_count += 1
                if agent_id in working_ids:
                    working_skipped += 1
                continue
            if if_running == "replace" and agent_id not in replaced_ids:
                close_warnings, closed_tmux_names = _close_live_agent_id(
                    agent_id,
                    live_agents,
                    live_tmux,
                )
                warnings.extend(close_warnings)
                live_tmux_names.difference_update(closed_tmux_names)
                live_ids.discard(agent_id)
                replaced_ids.add(agent_id)

        if kind in {"stygian", "hoplite"}:
            sess_name = str(entry.get("tmux_session", "")).strip()
            if sess_name and sess_name in live_tmux_names:
                if if_running == "error":
                    errors.append(f"tmux session already exists: {sess_name}")
                    continue
                if if_running == "skip":
                    skipped_count += 1
                    if agent_id in working_ids:
                        working_skipped += 1
                    continue
                if if_running == "replace":
                    if not _kill_tmux_session(sess_name):
                        errors.append(f"Failed to replace tmux session: {sess_name}")
                        continue
                    live_tmux_names.discard(sess_name)

        session_path = str(entry.get("session_path", "")).strip()
        if not session_path or not os.path.isfile(session_path):
            errors.append(
                f"Session file missing for {entry.get('name', '<unknown>')}: {session_path or '<empty>'}"
            )
            continue

        if kind == "kitty":
            ok, detail = _restore_kitty_entry(entry, workspace_mode=workspace_mode)
        elif kind in {"stygian", "hoplite"}:
            ok, detail = _restore_tmux_entry(entry)
        else:
            errors.append(f"Unknown snapshot entry kind: {kind or '<empty>'}")
            continue

        if ok:
            restored_count += 1
            if agent_id:
                live_ids.add(agent_id)
                if agent_id in working_ids:
                    working_restored += 1
            sess_name = str(entry.get("tmux_session", "")).strip()
            if sess_name:
                live_tmux_names.add(sess_name)
        else:
            errors.append(detail)

    return RestoreSnapshotResult(
        ok=not errors,
        path=snapshot_path,
        errors=errors,
        warnings=warnings,
        restored_count=restored_count,
        skipped_count=skipped_count,
        working_total=len(working_ids),
        working_restored=working_restored,
        working_skipped=working_skipped,
    )


def _snapshot_entry_for_kitty_agent(
    agent: AgentWindow,
    all_agents: list[AgentWindow],
) -> tuple[dict[str, Any], str | None]:
    agent_id = (agent.agent_id or "").strip()
    if not agent_id:
        return {}, f"Cannot snapshot {agent.name}: missing agent id"

    session_path, source = resolve_agent_session_path_with_source(agent)

    if source == "cwd":
        shared = [a for a in all_agents if not _is_stygian_agent(a) and a.cwd == agent.cwd]
        if len(shared) > 1:
            return {}, (
                "Cannot snapshot "
                f"{agent.name}: ambiguous cwd fallback shared by {len(shared)} Hippeis"
            )

    if not session_path or not os.path.isfile(session_path):
        return {}, (
            f"Cannot snapshot {agent.name}: missing restorable session path"
        )

    role = (agent.role or "").strip() or "hippeus"
    return {
        "kind": "kitty",
        "name": agent.name,
        "agent_id": agent_id,
        "role": role,
        "cwd": agent.cwd,
        "workspace": agent.workspace or "?",
        "session_path": session_path,
        "session_source": source,
        "parent_id": (agent.parent_id or "").strip(),
    }, None


def _snapshot_entry_for_stygian_agent(
    agent: AgentWindow,
) -> tuple[dict[str, Any], str | None]:
    agent_id = (agent.agent_id or "").strip()
    if not agent_id:
        return {}, f"Cannot snapshot {agent.name}: missing agent id"

    session_path = (agent.session_path or "").strip()
    source = "env"
    if not session_path:
        session_path = resolve_stygian_session_path(agent.tmux_session)
        source = "tmux"

    if not session_path or not os.path.isfile(session_path):
        return {}, f"Cannot snapshot {agent.name}: missing restorable Stygian session path"

    return {
        "kind": "stygian",
        "name": agent.name,
        "agent_id": agent_id,
        "role": "hippeus",
        "cwd": agent.cwd,
        "tmux_session": (agent.tmux_session or "").strip(),
        "session_path": session_path,
        "session_source": source,
    }, None


def _snapshot_entry_for_hoplite_session(
    sess: TmuxSession,
) -> tuple[dict[str, Any], str | None]:
    hoplite_id = (sess.agent_id or sess.env_agent_id or "").strip()
    if not hoplite_id:
        return {}, f"Cannot snapshot hoplite {sess.name}: missing hoplite agent id"

    session_path, source = _resolve_hoplite_session_path(sess, hoplite_id)
    if not session_path or not os.path.isfile(session_path):
        return {}, f"Cannot snapshot hoplite {sess.name}: missing restorable session path"

    return {
        "kind": "hoplite",
        "name": (sess.display_name or "").strip() or sess.name,
        "agent_id": hoplite_id,
        "role": "hoplite",
        "cwd": sess.cwd,
        "tmux_session": sess.name,
        "session_path": session_path,
        "session_source": source,
        "owner_id": (sess.owner_id or "").strip(),
        "phalanx_id": (sess.phalanx_id or "").strip(),
    }, None


def _resolve_hoplite_session_path(sess: TmuxSession, hoplite_id: str) -> tuple[str, str]:
    explicit = (sess.session_path or "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit, "tmux-option"

    runtime = read_runtime_session_path(hoplite_id)
    if runtime and os.path.isfile(runtime):
        return runtime, "runtime"

    extracted = _extract_session_path_from_command(sess.command)
    if extracted and os.path.isfile(extracted):
        return extracted, "start-command"

    return "", "none"


def _extract_session_path_from_command(command: str) -> str:
    if not command.strip():
        return ""
    match = re.search(r"(?:^|\s)ZEUS_SESSION_PATH=([^\s]+)(?:\s|$)", command)
    if not match:
        return ""
    return match.group(1).strip().strip('"\'')


def _is_hoplite_session_for(agent: AgentWindow, sess: TmuxSession) -> bool:
    if (sess.role or "").strip().lower() != "hoplite":
        return False
    owner_id = (sess.owner_id or "").strip()
    if not owner_id:
        return False
    if owner_id != (agent.agent_id or "").strip():
        return False
    return bool((sess.phalanx_id or "").strip())


def _is_stygian_agent(agent: AgentWindow) -> bool:
    return (
        (agent.backend or "").strip() == STYGIAN_AGENT_BACKEND
        and bool((agent.tmux_session or "").strip())
    )


def _snapshot_file_path(name: str) -> Path:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    clean = _slugify_snapshot_name(name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}-{clean}.json"
    candidate = SNAPSHOTS_DIR / base
    if not candidate.exists():
        return candidate

    for idx in range(1, 1000):
        candidate = SNAPSHOTS_DIR / f"{stamp}-{clean}-{idx}.json"
        if not candidate.exists():
            return candidate

    raise RuntimeError("Could not allocate unique snapshot file name")


def _slugify_snapshot_name(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-._")
    return clean or "snapshot"


def _close_snapshot_entries(
    entries: list[dict[str, Any]],
    live_agents: list[AgentWindow],
) -> tuple[int, list[str]]:
    closed = 0
    warnings: list[str] = []

    live_by_id: dict[str, AgentWindow] = {
        (agent.agent_id or "").strip(): agent
        for agent in live_agents
        if (agent.agent_id or "").strip()
    }

    closed_kitty_ids: set[str] = set()
    killed_tmux: set[str] = set()

    for entry in entries:
        kind = str(entry.get("kind", "")).strip().lower()
        if kind == "kitty":
            agent_id = str(entry.get("agent_id", "")).strip()
            if not agent_id or agent_id in closed_kitty_ids:
                continue
            live = live_by_id.get(agent_id)
            if live is None:
                warnings.append(f"Close skipped (not live): {entry.get('name', agent_id)}")
                continue
            close_window(live)
            closed += 1
            closed_kitty_ids.add(agent_id)
            continue

        if kind in {"stygian", "hoplite"}:
            session_name = str(entry.get("tmux_session", "")).strip()
            if not session_name or session_name in killed_tmux:
                continue
            if _kill_tmux_session(session_name):
                closed += 1
            else:
                warnings.append(f"Failed to close tmux session: {session_name}")
            killed_tmux.add(session_name)

    return closed, warnings


def _kill_tmux_session(session_name: str) -> bool:
    result = _run_tmux(["tmux", "kill-session", "-t", session_name], timeout=3)
    return result is not None and result.returncode == 0


def _tmux_agent_id_for_restore(sess: TmuxSession) -> str:
    """Return deterministic tmux agent id usable for restore conflict checks."""
    source = (sess.agent_id_source or "").strip().lower()
    if source not in {"option", "start-command"}:
        return ""
    return (sess.agent_id or "").strip()


def _close_live_agent_id(
    agent_id: str,
    live_agents: list[AgentWindow],
    live_tmux: list[TmuxSession],
) -> tuple[list[str], set[str]]:
    warnings: list[str] = []
    closed_tmux_names: set[str] = set()

    for agent in live_agents:
        if (agent.agent_id or "").strip() == agent_id:
            close_window(agent)

    for sess in live_tmux:
        sess_agent_id = _tmux_agent_id_for_restore(sess)
        if sess_agent_id != agent_id:
            continue
        if _kill_tmux_session(sess.name):
            closed_tmux_names.add(sess.name)
            continue
        warnings.append(f"Failed to replace tmux session: {sess.name}")

    return warnings, closed_tmux_names


def _restore_kitty_entry(entry: dict[str, Any], *, workspace_mode: str) -> tuple[bool, str]:
    name = str(entry.get("name", "")).strip()
    cwd = str(entry.get("cwd", "")).strip()
    agent_id = str(entry.get("agent_id", "")).strip()
    role = str(entry.get("role", "")).strip() or "hippeus"
    session_path = str(entry.get("session_path", "")).strip()
    parent_id = str(entry.get("parent_id", "")).strip()
    phalanx_id = str(entry.get("phalanx_id", "")).strip()
    workspace = str(entry.get("workspace", "")).strip()

    if not all((name, cwd, agent_id, session_path)):
        return False, f"Malformed kitty snapshot entry for {name or '<unnamed>'}"

    env = os.environ.copy()
    env["ZEUS_AGENT_NAME"] = name
    env["ZEUS_AGENT_ID"] = agent_id
    env["ZEUS_ROLE"] = role
    env["ZEUS_SESSION_PATH"] = session_path

    if parent_id:
        env["ZEUS_PARENT_ID"] = parent_id
    else:
        env.pop("ZEUS_PARENT_ID", None)

    if phalanx_id:
        env["ZEUS_PHALANX_ID"] = phalanx_id
    else:
        env.pop("ZEUS_PHALANX_ID", None)

    try:
        proc = subprocess.Popen(
            [
                "kitty",
                "--directory",
                cwd,
                "--hold",
                "bash",
                "-lc",
                f"pi --session {shlex.quote(session_path)}",
            ],
            env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as exc:
        return False, f"Failed to restore {name}: {exc}"

    if workspace_mode == "original" and workspace and workspace != "?":
        move_pid_to_workspace_and_focus_later(proc.pid, workspace, delay=0.5)

    return True, ""


def _restore_tmux_entry(entry: dict[str, Any]) -> tuple[bool, str]:
    kind = str(entry.get("kind", "")).strip().lower()
    session_name = str(entry.get("tmux_session", "")).strip()
    name = str(entry.get("name", "")).strip() or session_name
    cwd = str(entry.get("cwd", "")).strip()
    agent_id = str(entry.get("agent_id", "")).strip()
    role = str(entry.get("role", "")).strip() or ("hoplite" if kind == "hoplite" else "hippeus")
    session_path = str(entry.get("session_path", "")).strip()
    parent_id = str(entry.get("owner_id", "")).strip()
    phalanx_id = str(entry.get("phalanx_id", "")).strip()

    if not all((session_name, cwd, agent_id, session_path)):
        return False, f"Malformed tmux snapshot entry: {session_name or '<unnamed>'}"

    env_parts: list[str] = [
        f"ZEUS_AGENT_NAME={shlex.quote(name)}",
        f"ZEUS_AGENT_ID={shlex.quote(agent_id)}",
        f"ZEUS_ROLE={shlex.quote(role)}",
    ]
    if parent_id:
        env_parts.append(f"ZEUS_PARENT_ID={shlex.quote(parent_id)}")
    if phalanx_id:
        env_parts.append(f"ZEUS_PHALANX_ID={shlex.quote(phalanx_id)}")

    env_parts.append(f"ZEUS_SESSION_PATH={shlex.quote(session_path)}")
    start_command = " ".join(env_parts + [f"exec pi --session {shlex.quote(session_path)}"])

    created = _run_tmux(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", cwd, start_command],
        timeout=5,
    )
    if created is None or created.returncode != 0:
        detail = _tmux_error_detail(created)
        return False, f"Failed to restore tmux session {session_name}: {detail}"

    options: list[tuple[str, str]] = [
        ("@zeus_agent", agent_id),
        ("@zeus_role", role),
        ("@zeus_name", name),
        ("@zeus_session_path", session_path),
    ]

    if kind == "stygian":
        options.extend(
            [
                ("@zeus_backend", STYGIAN_TMUX_BACKEND_TAG),
                ("@zeus_owner", ""),
                ("@zeus_phalanx", ""),
            ]
        )
    elif kind == "hoplite":
        options.extend(
            [
                ("@zeus_backend", ""),
                ("@zeus_owner", parent_id),
                ("@zeus_phalanx", phalanx_id),
            ]
        )

    for option, value in options:
        result = _run_tmux(
            ["tmux", "set-option", "-t", session_name, option, value],
            timeout=3,
        )
        if result is None or result.returncode != 0:
            _kill_tmux_session(session_name)
            return False, f"Failed to set {option} for {session_name}: {_tmux_error_detail(result)}"

    return True, ""


def _run_tmux(
    command: list[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _tmux_error_detail(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "tmux unavailable"
    detail = (result.stderr or result.stdout or "").strip()
    return detail or f"exit={result.returncode}"


def _load_snapshot(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"Snapshot file not found: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Snapshot file unreadable: {exc}"

    if not isinstance(payload, dict):
        return None, "Snapshot payload must be an object"

    version = payload.get("schema_version")
    if version != SNAPSHOT_SCHEMA_VERSION:
        return None, (
            "Unsupported snapshot schema_version: "
            f"{version!r} (expected {SNAPSHOT_SCHEMA_VERSION})"
        )

    entries = payload.get("entries")
    if not isinstance(entries, list):
        return None, "Snapshot payload missing entries list"

    return payload, None
