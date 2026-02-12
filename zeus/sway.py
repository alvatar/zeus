"""Sway workspace discovery."""

from __future__ import annotations

import json
import subprocess


def build_pid_workspace_map() -> dict[int, str]:
    """Walk the sway tree and return {pid: workspace_name}."""
    try:
        r = subprocess.run(
            ["swaymsg", "-t", "get_tree"],
            capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return {}
        tree: dict = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}

    pid_ws: dict[int, str] = {}

    def walk(node: dict, workspace: str = "") -> None:
        if node.get("type") == "workspace":
            workspace = node.get("name", workspace)
        pid: int | None = node.get("pid")
        if pid:
            pid_ws[pid] = workspace
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child, workspace)

    walk(tree)
    return pid_ws
