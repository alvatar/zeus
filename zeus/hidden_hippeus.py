"""Hidden Hippeus backend (tmux-native agents without kitty windows)."""

from __future__ import annotations

from collections.abc import Mapping
import os
import re
import shlex
import subprocess

from .models import AgentWindow, TmuxSession
from .sessions import make_new_session_path

HIDDEN_AGENT_BACKEND = "tmux-hidden"
HIDDEN_TMUX_BACKEND_TAG = "hidden-hippeus"


def hidden_agent_row_key(agent_id: str) -> str:
    """Return stable dashboard row key for hidden agents."""
    return f"hidden:{agent_id.strip()}"


def hidden_tmux_session_name(agent_id: str) -> str:
    """Generate deterministic tmux session name from agent id."""
    clean = agent_id.strip()
    suffix = clean[:8] if clean else "agent"
    return f"hidden-{suffix}"


def is_hidden_tmux_session(session: TmuxSession) -> bool:
    """Return True when a tmux session is tagged as hidden Hippeus."""
    return (session.backend or "").strip().lower() == HIDDEN_TMUX_BACKEND_TAG


def _run_tmux(
    command: list[str],
    *,
    timeout: float = 3,
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


def _extract_session_path_from_start_command(command: str) -> str:
    if not command.strip():
        return ""
    match = re.search(r"(?:^|\s)ZEUS_SESSION_PATH=([^\s]+)(?:\s|$)", command)
    if not match:
        return ""
    return match.group(1).strip().strip('"\'')


def resolve_hidden_session_path(session_name: str) -> str:
    """Resolve hidden Hippeus session path from tmux metadata."""
    name = session_name.strip()
    if not name:
        return ""

    option = _run_tmux(
        ["tmux", "show-options", "-t", name, "-qv", "@zeus_session_path"],
        timeout=2,
    )
    if option is not None and option.returncode == 0:
        value = option.stdout.strip()
        if value:
            return value

    pane = _run_tmux(
        ["tmux", "list-panes", "-t", name, "-F", "#{pane_start_command}"],
        timeout=2,
    )
    if pane is None or pane.returncode != 0:
        return ""

    first = pane.stdout.splitlines()[0].strip() if pane.stdout else ""
    return _extract_session_path_from_start_command(first)


def launch_hidden_hippeus(
    *,
    name: str,
    directory: str,
    agent_id: str,
) -> tuple[str, str]:
    """Launch a detached tmux-backed Hippeus and stamp Zeus metadata."""
    clean_id = agent_id.strip()
    if not clean_id:
        raise ValueError("missing agent id")

    clean_name = name.strip() or clean_id
    cwd = os.path.expanduser(directory)
    session_name = hidden_tmux_session_name(clean_id)
    session_path = make_new_session_path(cwd)

    start_command = (
        f"ZEUS_AGENT_NAME={shlex.quote(clean_name)} "
        f"ZEUS_AGENT_ID={shlex.quote(clean_id)} "
        "ZEUS_ROLE=hippeus "
        f"ZEUS_SESSION_PATH={shlex.quote(session_path)} "
        f"exec pi --session {shlex.quote(session_path)}"
    )

    created = _run_tmux(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-c",
            cwd,
            start_command,
        ],
        timeout=5,
    )
    if created is None or created.returncode != 0:
        raise RuntimeError(_tmux_error_detail(created))

    option_values = [
        ("@zeus_backend", HIDDEN_TMUX_BACKEND_TAG),
        ("@zeus_agent", clean_id),
        ("@zeus_role", "hippeus"),
        ("@zeus_name", clean_name),
        ("@zeus_session_path", session_path),
    ]

    for option, value in option_values:
        result = _run_tmux(
            ["tmux", "set-option", "-t", session_name, option, value],
            timeout=3,
        )
        if result is None or result.returncode != 0:
            _run_tmux(["tmux", "kill-session", "-t", session_name], timeout=2)
            raise RuntimeError(
                f"set-option {option} failed: {_tmux_error_detail(result)}"
            )

    return session_name, session_path


def discover_hidden_agents(
    tmux_sessions: list[TmuxSession],
    *,
    name_overrides: Mapping[str, str] | None = None,
) -> tuple[list[AgentWindow], list[TmuxSession]]:
    """Build hidden-agent rows from tagged tmux sessions.

    Returns ``(hidden_agents, remaining_tmux_sessions)`` where remaining sessions
    exclude hidden ones (so they aren't rendered as viewer child rows).
    """
    overrides = dict(name_overrides or {})

    hidden_by_id: dict[str, TmuxSession] = {}
    remaining: list[TmuxSession] = []

    for sess in tmux_sessions:
        if not is_hidden_tmux_session(sess):
            remaining.append(sess)
            continue

        sess_agent_id = (sess.agent_id or sess.env_agent_id or "").strip()
        if not sess_agent_id:
            remaining.append(sess)
            continue

        prev = hidden_by_id.get(sess_agent_id)
        if prev is None or sess.created > prev.created:
            hidden_by_id[sess_agent_id] = sess

    hidden_agents: list[AgentWindow] = []
    for agent_id, sess in sorted(hidden_by_id.items(), key=lambda item: item[1].name):
        row_key = hidden_agent_row_key(agent_id)
        default_name = (sess.display_name or "").strip() or f"hidden-{agent_id[:4]}"
        display_name = overrides.get(row_key, default_name)

        hidden_agents.append(
            AgentWindow(
                kitty_id=0,
                socket="",
                name=display_name,
                pid=max(0, sess.pane_pid),
                kitty_pid=0,
                cwd=sess.cwd,
                agent_id=agent_id,
                role="hippeus",
                session_path=sess.session_path,
                backend=HIDDEN_AGENT_BACKEND,
                tmux_session=sess.name,
            )
        )

    return hidden_agents, remaining


def capture_hidden_screen_text(
    session_name: str,
    *,
    full: bool = False,
    ansi: bool = False,
) -> str:
    """Capture hidden Hippeus output from tmux pane history."""
    start = "-" if full else "-200"
    command = ["tmux", "capture-pane", "-t", session_name, "-p"]
    if ansi:
        command.append("-e")
    command.extend(["-S", start])

    result = _run_tmux(command, timeout=3)
    if result is None or result.returncode != 0:
        return ""
    return result.stdout


def send_hidden_text(session_name: str, text: str, *, queue: bool) -> bool:
    """Send text to hidden Hippeus (Enter or Alt+Enter queue)."""
    key = "M-Enter" if queue else "Enter"
    result = _run_tmux(
        ["tmux", "send-keys", "-t", session_name, text, key],
        timeout=3,
    )
    return result is not None and result.returncode == 0


def send_hidden_escape(session_name: str) -> bool:
    """Send ESC to hidden Hippeus pane."""
    result = _run_tmux(
        ["tmux", "send-keys", "-t", session_name, "Escape"],
        timeout=3,
    )
    return result is not None and result.returncode == 0


def kill_hidden_session(session_name: str) -> tuple[bool, str]:
    """Kill hidden Hippeus tmux session."""
    result = _run_tmux(["tmux", "kill-session", "-t", session_name], timeout=3)
    if result is None or result.returncode != 0:
        return False, _tmux_error_detail(result)
    return True, ""
