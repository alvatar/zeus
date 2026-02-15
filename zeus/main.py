"""CLI entry point: argument parsing and dispatch."""

import argparse

from .commands import cmd_new, cmd_ls, cmd_focus, cmd_kill
from .dashboard import cmd_dashboard
from .usage import fetch_openai_usage, fetch_claude_usage


def main():
    parser = argparse.ArgumentParser(
        prog="zeus",
        description="Monitor and manage coding agents in kitty windows",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_new = sub.add_parser("new", help="Launch a new tracked agent window")
    p_new.add_argument("-n", "--name", required=True, help="Agent name")
    p_new.add_argument("-d", "--directory", help="Working directory")
    p_new.set_defaults(func=cmd_new)

    p_ls = sub.add_parser("ls", help="List tracked agent windows")
    p_ls.set_defaults(func=cmd_ls)

    p_focus = sub.add_parser("focus", help="Focus an agent window")
    p_focus.add_argument("id", help="Window ID or name")
    p_focus.set_defaults(func=cmd_focus)

    p_kill = sub.add_parser("kill", help="Close an agent window")
    p_kill.add_argument("id", help="Window ID or name")
    p_kill.set_defaults(func=cmd_kill)

    # Hidden/internal commands
    p_fetch_openai = sub.add_parser(
        "fetch-openai-usage", help=argparse.SUPPRESS
    )
    p_fetch_openai.set_defaults(func=lambda _args: fetch_openai_usage())

    p_fetch_claude = sub.add_parser(
        "fetch-claude-usage", help=argparse.SUPPRESS
    )
    p_fetch_claude.set_defaults(func=lambda _args: fetch_claude_usage())

    p_dash = sub.add_parser("dashboard", aliases=["d"], help="Live dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        cmd_dashboard(args)
