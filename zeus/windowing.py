"""Sway/process window helpers."""

from __future__ import annotations

import subprocess
import threading
import time


def run_swaymsg(*args: str, timeout: float = 3) -> bool:
    """Run swaymsg command, return True on success."""
    try:
        r = subprocess.run(
            ["swaymsg", *args],
            capture_output=True,
            timeout=timeout,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def focus_pid(pid: int, timeout: float = 3) -> bool:
    """Focus sway window containing ``pid``."""
    return run_swaymsg(f"[pid={pid}]", "focus", timeout=timeout)


def kill_pid(pid: int, timeout: float = 3) -> bool:
    """Kill sway window containing ``pid``."""
    return run_swaymsg(f"[pid={pid}]", "kill", timeout=timeout)


def move_pid_to_workspace_and_focus(
    pid: int,
    workspace: str,
    timeout: float = 3,
) -> bool:
    """Move a PID to workspace, switch to workspace, and focus PID."""
    if not workspace or workspace == "?":
        return False
    moved = run_swaymsg(
        f"[pid={pid}]", "move", "workspace", workspace, timeout=timeout,
    )
    switched = run_swaymsg("workspace", workspace, timeout=timeout)
    focused = run_swaymsg(f"[pid={pid}]", "focus", timeout=timeout)
    return moved and switched and focused


def move_pid_to_workspace_and_focus_later(
    pid: int,
    workspace: str,
    delay: float = 0.5,
    timeout: float = 3,
) -> None:
    """Schedule move/focus after a delay in a daemon thread."""
    if not workspace or workspace == "?":
        return

    def _worker() -> None:
        time.sleep(delay)
        move_pid_to_workspace_and_focus(pid, workspace, timeout=timeout)

    threading.Thread(target=_worker, daemon=True).start()


def _read_parent_pid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("PPid:"):
                    ppid = int(line.split()[1])
                    return ppid if ppid > 1 else None
    except (FileNotFoundError, ValueError, IndexError, PermissionError):
        return None
    return None


def _read_comm(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError):
        return None


def find_ancestor_pid_by_comm(
    start_pid: int,
    comm_name: str,
    max_hops: int = 15,
) -> int | None:
    """Walk parent chain and return first PID whose comm equals ``comm_name``."""
    pid = start_pid
    for _ in range(max_hops):
        comm = _read_comm(pid)
        if comm == comm_name:
            return pid
        ppid = _read_parent_pid(pid)
        if ppid is None:
            break
        pid = ppid
    return None
