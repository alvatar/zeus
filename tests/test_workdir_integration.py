"""Integration tests for workdir agent spawn, merge cleanup, and consolidation.

These tests verify the dashboard integration paths that have historically failed:
- Workdir spawn uses pi --session (not pipe, not --prompt)
- Workdir prompt delivered via enqueue_envelope (not hallucinated enqueue_message)
- Consolidation _start_consolidation_timeout not called from worker thread
- Merge cleanup purges queue messages for dead agent
- Confirm-replace callback fires correctly
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zeus.worktree import (
    create_worktree,
    get_current_branch,
    remove_worktree,
    worktree_path,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> str:
    """Create a temporary git repo with one commit."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    (Path(repo) / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return repo


# ── Workdir spawn uses pi --session ──────────────────────────────────


def test_spawn_uses_pi_session_not_pipe(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_spawn_workdir_blocking must launch pi --session, never cat|pi or --prompt."""
    from zeus.dashboard.app import ZeusApp

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "workdir-agent.md").write_text("prompt for <agent_name>")
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    mock_proc = MagicMock(pid=999)
    real_popen = subprocess.Popen
    mock_popen = MagicMock(return_value=mock_proc)

    def selective_popen(cmd, **kwargs):
        if cmd and cmd[0] == "kitty":
            return mock_popen(cmd, **kwargs)
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", selective_popen)
    monkeypatch.setattr("zeus.dashboard.app.enqueue_envelope", MagicMock())

    agent = MagicMock()
    agent.cwd = git_repo
    agent.agent_id = "parent-123"
    agent.workspace = ""

    app = ZeusApp.__new__(ZeusApp)
    app._spawn_workdir_blocking(agent, "wt-test")

    cmd = mock_popen.call_args[0][0]
    bash_cmd = cmd[-1]

    # MUST use --session
    assert "pi --session" in bash_cmd, f"Expected 'pi --session', got: {bash_cmd}"

    # MUST NOT pipe stdin or use --prompt
    assert "| pi" not in bash_cmd, f"Must not pipe stdin: {bash_cmd}"
    assert "--prompt" not in bash_cmd, f"Must not use --prompt (doesn't exist): {bash_cmd}"

    # MUST set ZEUS_SESSION_PATH in env
    env = mock_popen.call_args[1]["env"]
    assert "ZEUS_SESSION_PATH" in env, "Missing ZEUS_SESSION_PATH env var"

    remove_worktree(git_repo, "wt-test")


# ── Workdir prompt uses real enqueue_envelope API ─────────────────────


def test_spawn_enqueues_via_real_api(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prompt must be enqueued via OutboundEnvelope.new + enqueue_envelope."""
    from zeus.dashboard.app import ZeusApp

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "workdir-agent.md").write_text("You are <agent_name>")
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    mock_proc = MagicMock(pid=1)
    real_popen = subprocess.Popen
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda cmd, **kw: MagicMock(pid=1) if cmd and cmd[0] == "kitty" else real_popen(cmd, **kw),
    )

    mock_enqueue = MagicMock()
    monkeypatch.setattr("zeus.dashboard.app.enqueue_envelope", mock_enqueue)

    agent = MagicMock(cwd=git_repo, agent_id="p1", workspace="")
    app = ZeusApp.__new__(ZeusApp)
    app._spawn_workdir_blocking(agent, "api-test")

    assert mock_enqueue.called, "enqueue_envelope was never called"
    envelope = mock_enqueue.call_args[0][0]
    # Verify it's a real OutboundEnvelope, not some random dict
    assert hasattr(envelope, "target_agent_id"), "Envelope is not an OutboundEnvelope"
    assert hasattr(envelope, "message"), "Envelope is not an OutboundEnvelope"
    assert "api-test" in envelope.message
    assert "<agent_name>" not in envelope.message, "Template placeholders not replaced"

    remove_worktree(git_repo, "api-test")


# ── Consolidation timeout not called from worker thread ───────────────


def test_consolidation_blocking_does_not_call_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_do_spawn_consolidation_blocking must NOT call _start_consolidation_timeout.

    The timeout uses asyncio.ensure_future which requires the main event loop.
    Calling it from asyncio.to_thread (worker thread) raises
    'no current event loop in thread'.
    """
    from zeus.dashboard.app import ZeusApp
    import inspect

    source = inspect.getsource(ZeusApp._do_spawn_consolidation_blocking)
    assert "_start_consolidation_timeout" not in source, (
        "_do_spawn_consolidation_blocking must not call _start_consolidation_timeout "
        "(it runs in a worker thread, asyncio.ensure_future needs the main loop)"
    )
    assert "asyncio" not in source, (
        "_do_spawn_consolidation_blocking must not use asyncio "
        "(it runs in a worker thread)"
    )


def test_consolidation_timeout_called_from_async_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_spawn_consolidation_agent (async) must call _start_consolidation_timeout."""
    from zeus.dashboard.app import ZeusApp
    import inspect

    source = inspect.getsource(ZeusApp._spawn_consolidation_agent)
    assert "_start_consolidation_timeout" in source, (
        "_spawn_consolidation_agent must call _start_consolidation_timeout "
        "(it runs on the main event loop thread)"
    )


def test_consolidation_blocking_runs_in_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_do_spawn_consolidation_blocking must actually work from a thread without asyncio errors."""
    from zeus.dashboard.app import ZeusApp
    import concurrent.futures

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "consolidation-project.md").write_text(
        "Consolidate project <project_name>."
    )
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    # Mock subprocess.run so we don't actually launch tmux
    captured_cmds: list[list[str]] = []
    real_run = subprocess.run
    def mock_run(cmd, **kwargs):
        if cmd and cmd[0] == "tmux":
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0)
        return real_run(cmd, **kwargs)
    monkeypatch.setattr("subprocess.run", mock_run)

    app = ZeusApp.__new__(ZeusApp)

    params = {"type": "project", "model_spec": "", "topic": ""}

    # Run in a thread pool — same as asyncio.to_thread does
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(app._do_spawn_consolidation_blocking, params)
        result = future.result(timeout=10)

    assert result is not None
    agent_id, tmux_name = result
    assert agent_id
    assert tmux_name.startswith("zeus-cons-")

    # Verify the tmux command uses bash -lc with positional arg, not pipe
    new_session_cmd = captured_cmds[0]
    shell_cmd = new_session_cmd[-1]
    assert "bash -lc" in shell_cmd, f"Must use bash -lc, got: {shell_cmd}"
    assert "| pi" not in shell_cmd, f"Must not pipe stdin: {shell_cmd}"
    assert "pi" in shell_cmd


def test_consolidation_with_model_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consolidation with model_spec must pass --model to pi."""
    from zeus.dashboard.app import ZeusApp
    import concurrent.futures

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "consolidation-project.md").write_text(
        "Consolidate <project_name>."
    )
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    captured_cmds: list[list[str]] = []
    real_run = subprocess.run
    def mock_run(cmd, **kwargs):
        if cmd and cmd[0] == "tmux":
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0)
        return real_run(cmd, **kwargs)
    monkeypatch.setattr("subprocess.run", mock_run)

    app = ZeusApp.__new__(ZeusApp)
    params = {"type": "project", "model_spec": "anthropic/claude-opus-4-6", "topic": ""}

    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(app._do_spawn_consolidation_blocking, params)
        result = future.result(timeout=10)

    assert result is not None
    shell_cmd = captured_cmds[0][-1]
    assert "--model" in shell_cmd
    assert "anthropic/claude-opus-4-6" in shell_cmd


# ── Merge cleanup purges queue ────────────────────────────────────────


def test_merge_done_purges_queue(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_check_worktree_merge_done must purge pending queue messages for the agent."""
    from zeus.dashboard.app import ZeusApp
    from zeus.message_queue import OutboundEnvelope

    # Create worktree to clean up
    create_worktree(git_repo, "purge-test", base_branch="main")

    # Set up bus inbox with merge signal
    bus_dir = tmp_path / "agent-bus" / "inbox" / "zeus" / "new"
    bus_dir.mkdir(parents=True)
    (bus_dir / "signal.json").write_text(json.dumps({
        "type": "worktree_merge_done",
        "agent_id": "dead-agent-id",
        "agent_name": "purge-test",
        "repo_root": git_repo,
    }))

    # Set up queue with a pending message for the dead agent
    queue_dir = tmp_path / "queue" / "new"
    queue_dir.mkdir(parents=True)
    monkeypatch.setattr("zeus.config.AGENT_BUS_INBOX_DIR", tmp_path / "agent-bus" / "inbox")

    mock_purge = MagicMock()
    app = ZeusApp.__new__(ZeusApp)
    app._agent_windows = []
    app.notify = MagicMock()
    app._purge_queue_for_agent = mock_purge

    app._check_worktree_merge_done()

    # Must have called _purge_queue_for_agent with the dead agent's ID
    mock_purge.assert_called_once_with("dead-agent-id")


# ── Confirm-replace dismiss result ───────────────────────────────────


def test_confirm_worktree_replace_returns_bool() -> None:
    """ConfirmWorktreeReplaceScreen.dismiss must pass True on confirm, False on cancel."""
    from zeus.dashboard.screens import ConfirmWorktreeReplaceScreen

    screen = ConfirmWorktreeReplaceScreen("test", "/tmp/test")

    # Verify action_confirm dismisses with True
    dismiss_calls: list[object] = []
    screen.dismiss = lambda result=None: dismiss_calls.append(result)  # type: ignore[assignment]

    screen.action_confirm()
    assert dismiss_calls == [True]

    dismiss_calls.clear()
    screen.action_cancel()
    assert dismiss_calls == [False]


# ── Workdir env vars match NewAgentScreen pattern ─────────────────────


def test_spawn_env_vars_match_new_agent_pattern(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workdir spawn must set the same env vars as NewAgentScreen."""
    from zeus.dashboard.app import ZeusApp

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "workdir-agent.md").write_text("x")
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    captured_env: dict[str, str] = {}
    real_popen = subprocess.Popen

    def capture_popen(cmd, **kwargs):
        if cmd and cmd[0] == "kitty":
            captured_env.update(kwargs.get("env", {}))
            return MagicMock(pid=1)
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", capture_popen)
    monkeypatch.setattr("zeus.dashboard.app.enqueue_envelope", MagicMock())

    agent = MagicMock(cwd=git_repo, agent_id="p1", workspace="")
    app = ZeusApp.__new__(ZeusApp)
    app._spawn_workdir_blocking(agent, "env-test")

    # Required env vars (same set as NewAgentScreen._do_invoke)
    required = ["ZEUS_AGENT_NAME", "ZEUS_AGENT_ID", "ZEUS_ROLE", "ZEUS_SESSION_PATH"]
    for key in required:
        assert key in captured_env, f"Missing required env var: {key}"

    assert captured_env["ZEUS_AGENT_NAME"] == "env-test"
    assert captured_env["ZEUS_ROLE"] == "hippeus"
    # Workdir-specific extras
    assert "ZEUS_PARENT_BRANCH" in captured_env
    assert "ZEUS_PARENT_ID" in captured_env

    remove_worktree(git_repo, "env-test")
