"""CLI subcommands: new, ls, focus, kill."""

import os
import subprocess
import sys

from .kitty import discover_agents, focus_window, close_window, get_screen_text
from .state import detect_state, parse_footer
from .sway import build_pid_workspace_map


def cmd_new(args):
    name = args.name
    directory = os.path.expanduser(args.directory or os.getcwd())
    env = os.environ.copy()
    env["AGENTMON_NAME"] = name
    cmd = ["kitty", "--directory", directory, "--hold", "bash", "-lc", "pi"]
    subprocess.Popen(
        cmd, env=env, start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'✓ Launched "{name}" with pi in {directory}')


def cmd_ls(args):
    agents = discover_agents()
    if not agents:
        print("No tracked agents. Launch with: zeus new -n 'name'")
        return
    pid_ws = build_pid_workspace_map()
    for a in agents:
        screen = get_screen_text(a)
        a.state = detect_state(screen)
        a.model, a.ctx_pct, a.tokens_in, a.tokens_out = parse_footer(screen)
        a.workspace = pid_ws.get(a.kitty_pid, "?")
        cwd = a.cwd
        icon = {"WORKING": "▶", "IDLE": "⏹"}[a.state.value]
        print(
            f"  {icon} [{a.kitty_id}] {a.name:16s} {a.state.value:7s}  "
            f"{a.model or '—':20s} Ctx:{a.ctx_pct:.0f}%  "
            f"WS:{a.workspace:3s}  {cwd}"
        )


def cmd_focus(args):
    for a in discover_agents():
        if str(a.kitty_id) == args.id or a.name == args.id:
            focus_window(a)
            print(f'✓ Focused "{a.name}"')
            return
    print(f'✗ "{args.id}" not found')
    sys.exit(1)


def cmd_kill(args):
    for a in discover_agents():
        if str(a.kitty_id) == args.id or a.name == args.id:
            close_window(a)
            print(f'✓ Closed "{a.name}"')
            return
    print(f'✗ "{args.id}" not found')
    sys.exit(1)
