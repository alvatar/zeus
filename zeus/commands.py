"""CLI subcommands: new, ls, focus, kill."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys

from .kitty import (
    close_window,
    discover_agents,
    focus_window,
    generate_agent_id,
    get_screen_text,
)
from .state import detect_state, parse_footer
from .sway import build_pid_workspace_map
from .sessions import make_new_session_path
from .tmux import ensure_tmux_update_environment


def cmd_new(args: argparse.Namespace) -> None:
    ensure_tmux_update_environment()
    ensure_tmux_update_environment("ZEUS_ROLE")
    name: str = args.name
    directory: str = os.path.expanduser(args.directory or os.getcwd())
    env: dict[str, str] = os.environ.copy()
    env["ZEUS_AGENT_NAME"] = name
    env["ZEUS_AGENT_ID"] = generate_agent_id()
    env["ZEUS_ROLE"] = "hippeus"

    session_path = make_new_session_path(directory)
    env["ZEUS_SESSION_PATH"] = session_path

    cmd: list[str] = [
        "kitty",
        "--directory",
        directory,
        "--hold",
        "bash",
        "-lc",
        f"pi --session {shlex.quote(session_path)}",
    ]
    subprocess.Popen(
        cmd, env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'✓ Launched "{name}" with pi in {directory}')


def cmd_ls(args: argparse.Namespace) -> None:
    agents = discover_agents()
    if not agents:
        print("No tracked Hippeis. Launch with: zeus new -n 'name'")
        return
    pid_ws = build_pid_workspace_map()
    for a in agents:
        screen: str = get_screen_text(a)
        a.state = detect_state(screen)
        a.model, a.ctx_pct, a.tokens_in, a.tokens_out = parse_footer(screen)
        a.workspace = pid_ws.get(a.kitty_pid, "?")
        icon: str = {"WORKING": "▶", "IDLE": "⏹"}[a.state.value]
        print(
            f"  {icon} [{a.kitty_id}] {a.name:16s} {a.state.value:7s}  "
            f"{a.model or '—':20s} Ctx:{a.ctx_pct:.0f}%  "
            f"WS:{a.workspace:3s}  {a.cwd}"
        )


def cmd_focus(args: argparse.Namespace) -> None:
    for a in discover_agents():
        if str(a.kitty_id) == args.id or a.name == args.id:
            focus_window(a)
            print(f'✓ Focused "{a.name}"')
            return
    print(f'✗ "{args.id}" not found')
    sys.exit(1)


def cmd_kill(args: argparse.Namespace) -> None:
    for a in discover_agents():
        if str(a.kitty_id) == args.id or a.name == args.id:
            close_window(a)
            print(f'✓ Closed "{a.name}"')
            return
    print(f'✗ "{args.id}" not found')
    sys.exit(1)
