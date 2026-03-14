"""Shell launch helpers for Zeus-spawned Pi processes."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import pwd
import shlex

_DEFAULT_SHELL = "/bin/sh"


def resolve_user_shell(env: Mapping[str, str] | None = None) -> str:
    """Resolve the user's preferred shell for spawned agents.

    Zeus is often launched from GUI/tmux contexts whose environment is missing
    provider API keys that are only exported by the user's shell startup files.
    Launching Pi through the real interactive login shell lets those exports load
    before ``pi`` starts.
    """
    source = env if env is not None else os.environ
    candidate = str(source.get("SHELL") or "").strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_absolute() and path.exists():
            return str(path)

    try:
        passwd_shell = (pwd.getpwuid(os.getuid()).pw_shell or "").strip()
    except (KeyError, OSError):
        passwd_shell = ""
    if passwd_shell:
        path = Path(passwd_shell).expanduser()
        if path.is_absolute() and path.exists():
            return str(path)

    return _DEFAULT_SHELL


def user_shell_command_argv(
    command: str,
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build argv for running a command via the user's interactive login shell."""
    shell = resolve_user_shell(env)
    shell_name = Path(shell).name
    if shell_name == "fish":
        return [shell, "-i", "-l", "-c", command]
    return [shell, "-ilc", command]


def user_shell_command_string(
    command: str,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return a shell-quoted command string for tmux launch commands."""
    return shlex.join(user_shell_command_argv(command, env=env))


def kitty_hold_command_argv(
    cwd: str,
    command: str,
    *,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """Build argv for launching a held kitty window via the user's shell."""
    return [
        "kitty",
        "--directory",
        cwd,
        "--hold",
        *user_shell_command_argv(command, env=env),
    ]
