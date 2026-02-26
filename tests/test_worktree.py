"""Tests for zeus.worktree — git worktree helpers + dashboard spawn integration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zeus.worktree import (
    build_worktree_review,
    create_worktree,
    get_current_branch,
    get_repo_root,
    remove_worktree,
    worktree_base_dir,
    worktree_branch,
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
    # Need at least one commit for worktrees to work
    (Path(repo) / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    return repo


# ── Path helpers ─────────────────────────────────────────────────────


def test_worktree_path_format(git_repo: str) -> None:
    assert worktree_path(git_repo, "my-agent") == os.path.join(git_repo, ".worktrees", "my-agent")


def test_worktree_branch_format() -> None:
    assert worktree_branch("my-agent") == "zeus/my-agent"


def test_worktree_base_dir(git_repo: str) -> None:
    assert worktree_base_dir(git_repo) == os.path.join(git_repo, ".worktrees")


# ── Repo detection ───────────────────────────────────────────────────


def test_get_repo_root(git_repo: str) -> None:
    assert get_repo_root(git_repo) == git_repo


def test_get_repo_root_not_a_repo(tmp_path: Path) -> None:
    assert get_repo_root(str(tmp_path)) == ""


def test_get_current_branch(git_repo: str) -> None:
    assert get_current_branch(git_repo) == "main"


# ── Create worktree ──────────────────────────────────────────────────


def test_create_worktree(git_repo: str) -> None:
    ok, msg = create_worktree(git_repo, "test-agent")
    assert ok, msg
    wt = worktree_path(git_repo, "test-agent")
    assert os.path.isdir(wt)
    assert os.path.isfile(os.path.join(wt, "README.md"))
    # Branch was created
    branch = get_current_branch(wt)
    assert branch == "zeus/test-agent"


def test_create_worktree_adds_gitignore(git_repo: str) -> None:
    create_worktree(git_repo, "test-agent")
    gitignore = Path(git_repo) / ".gitignore"
    assert gitignore.exists()
    assert ".worktrees" in gitignore.read_text()


def test_create_worktree_duplicate_fails(git_repo: str) -> None:
    ok, _ = create_worktree(git_repo, "dup")
    assert ok
    ok2, msg2 = create_worktree(git_repo, "dup")
    assert not ok2
    assert "already exists" in msg2


def test_create_worktree_from_specific_branch(git_repo: str) -> None:
    ok, _ = create_worktree(git_repo, "from-main", base_branch="main")
    assert ok
    wt = worktree_path(git_repo, "from-main")
    assert get_current_branch(wt) == "zeus/from-main"


# ── Remove worktree ─────────────────────────────────────────────────


def test_remove_worktree(git_repo: str) -> None:
    create_worktree(git_repo, "to-remove")
    wt = worktree_path(git_repo, "to-remove")
    assert os.path.isdir(wt)

    ok, msg = remove_worktree(git_repo, "to-remove")
    assert ok, msg
    assert not os.path.isdir(wt)

    # Branch should be gone
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "zeus/to-remove"],
        capture_output=True, cwd=git_repo,
    )
    assert r.returncode != 0


def test_remove_nonexistent_worktree(git_repo: str) -> None:
    ok, msg = remove_worktree(git_repo, "nonexistent")
    # Should not crash, just report errors
    assert not ok or "not found" in msg.lower() or "nonexistent" in msg.lower()


# ── Merge ────────────────────────────────────────────────────────────


def test_merge_clean(git_repo: str) -> None:
    from zeus.worktree import merge_worktree_branch

    create_worktree(git_repo, "feature")
    wt = worktree_path(git_repo, "feature")

    # Make a change in the worktree
    (Path(wt) / "new-file.txt").write_text("feature work")
    subprocess.run(["git", "add", "new-file.txt"], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "feature commit"], cwd=wt, capture_output=True, check=True)

    ok, msg = merge_worktree_branch(git_repo, "feature", target_branch="main")
    assert ok, msg
    # File should now exist on main
    assert (Path(git_repo) / "new-file.txt").exists()


def test_merge_conflict_detected(git_repo: str) -> None:
    from zeus.worktree import merge_worktree_branch

    create_worktree(git_repo, "conflict-test")
    wt = worktree_path(git_repo, "conflict-test")

    # Change same file in both main and worktree
    (Path(git_repo) / "README.md").write_text("main change")
    subprocess.run(["git", "add", "README.md"], cwd=git_repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "main edit"], cwd=git_repo, capture_output=True, check=True)

    (Path(wt) / "README.md").write_text("worktree change")
    subprocess.run(["git", "add", "README.md"], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "wt edit"], cwd=wt, capture_output=True, check=True)

    ok, msg = merge_worktree_branch(git_repo, "conflict-test", target_branch="main")
    assert not ok
    assert "conflict" in msg.lower()

    # Repo should be clean (merge aborted) — only untracked .gitignore allowed
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=git_repo,
    )
    lines = [l for l in r.stdout.strip().splitlines() if not l.endswith(".gitignore")]
    assert lines == []


def test_build_worktree_review_uses_pr_style_ranges(git_repo: str) -> None:
    create_worktree(git_repo, "review-test", base_branch="main")
    wt = worktree_path(git_repo, "review-test")

    readme = Path(wt) / "README.md"
    readme.write_text("review change\n")
    subprocess.run(["git", "add", "README.md"], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "review commit"], cwd=wt, capture_output=True, check=True)

    ok, out = build_worktree_review(wt, use_delta=False)

    assert ok, out
    assert "=== WORKTREE REVIEW ===" in out
    assert "=== COMMITS (base..branch) ===" in out
    assert "=== FULL DIFF (base...branch) ===" in out
    assert "ranges: commits=main..zeus/review-test diff=main...zeus/review-test" in out
    assert "+review change" in out
    assert "=== REVIEW OUTPUT STATS ===" not in out
    assert out.rstrip().endswith("=== END OF REVIEW ===")

    remove_worktree(git_repo, "review-test")


def test_build_worktree_review_passes_delta_width_to_delta(
    git_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_worktree(git_repo, "review-width", base_branch="main")
    wt = worktree_path(git_repo, "review-width")

    payload = Path(wt) / "README.md"
    payload.write_text("review width\n")
    subprocess.run(["git", "add", "README.md"], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "review width"], cwd=wt, capture_output=True, check=True)

    real_run = subprocess.run
    delta_calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):  # noqa: ANN001
        if isinstance(cmd, list) and cmd and cmd[0] == "delta":
            delta_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="delta-rendered", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("zeus.worktree.shutil.which", lambda tool: "/usr/bin/delta" if tool == "delta" else None)
    monkeypatch.setattr("zeus.worktree.subprocess.run", _run)

    ok, out = build_worktree_review(wt, delta_width=157)

    assert ok
    assert "delta-rendered" in out
    assert out.rstrip().endswith("=== END OF REVIEW ===")
    assert delta_calls
    assert "--side-by-side" in delta_calls[0]
    assert "--dark" in delta_calls[0]
    assert "--file-decoration-style" in delta_calls[0]
    assert "--hunk-header-decoration-style" in delta_calls[0]
    assert "box #5a5a5a" in delta_calls[0]
    assert "--line-numbers-left-style" in delta_calls[0]
    assert "--line-numbers-right-style" in delta_calls[0]
    assert "#5a5a5a" in delta_calls[0]
    assert "--width=157" in delta_calls[0]

    remove_worktree(git_repo, "review-width")


def test_build_worktree_review_light_mode_uses_dark_delta_rendering(
    git_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_worktree(git_repo, "review-light", base_branch="main")
    wt = worktree_path(git_repo, "review-light")

    payload = Path(wt) / "README.md"
    payload.write_text("review light\n")
    subprocess.run(["git", "add", "README.md"], cwd=wt, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "review light"], cwd=wt, capture_output=True, check=True)

    real_run = subprocess.run
    delta_calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):  # noqa: ANN001
        if isinstance(cmd, list) and cmd and cmd[0] == "delta":
            delta_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="delta-rendered", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("zeus.worktree.shutil.which", lambda tool: "/usr/bin/delta" if tool == "delta" else None)
    monkeypatch.setattr("zeus.worktree.subprocess.run", _run)

    ok, out = build_worktree_review(wt, delta_theme_mode="light")

    assert ok
    assert "delta-rendered" in out
    assert out.rstrip().endswith("=== END OF REVIEW ===")
    assert delta_calls
    assert "--side-by-side" in delta_calls[0]
    assert "--dark" in delta_calls[0]
    assert "--light" not in delta_calls[0]
    assert "--file-decoration-style" in delta_calls[0]
    assert "--hunk-header-decoration-style" in delta_calls[0]
    assert "box #5a5a5a" in delta_calls[0]
    assert "--line-numbers-left-style" in delta_calls[0]
    assert "--line-numbers-right-style" in delta_calls[0]
    assert "#5a5a5a" in delta_calls[0]
    assert "--map-styles" not in delta_calls[0]

    remove_worktree(git_repo, "review-light")


def test_build_worktree_review_excludes_uncommitted_changes(git_repo: str) -> None:
    create_worktree(git_repo, "dirty-review", base_branch="main")
    wt = worktree_path(git_repo, "dirty-review")

    dirty = Path(wt) / "README.md"
    dirty.write_text("dirty uncommitted change\n")

    ok, out = build_worktree_review(wt, use_delta=False)

    assert ok, out
    assert "warning: worktree has uncommitted changes" in out
    assert "dirty uncommitted change" not in out

    remove_worktree(git_repo, "dirty-review")


def test_build_worktree_review_requires_worktree_checkout(git_repo: str) -> None:
    ok, out = build_worktree_review(git_repo, use_delta=False)
    assert not ok
    assert "not a git worktree" in out.lower()


# ── Dashboard spawn integration ──────────────────────────────────────


def test_build_workdir_prompt_fills_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_workdir_prompt must fill all template placeholders."""
    from zeus.dashboard.app import ZeusApp

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "workdir-agent.md").write_text(
        "Agent <agent_name> on branch <branch_name> in <worktree_path> (repo <repo_root>, parent <parent_branch>)"
    )
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    app = ZeusApp.__new__(ZeusApp)
    result = app._build_workdir_prompt(
        name="test-wt",
        parent_branch="main",
        branch="zeus/test-wt",
        wt_path="/tmp/wt",
        repo_root="/tmp/repo",
    )

    assert "test-wt" in result
    assert "zeus/test-wt" in result
    assert "/tmp/wt" in result
    assert "/tmp/repo" in result
    assert "<agent_name>" not in result
    assert "<branch_name>" not in result


def test_spawn_workdir_blocking_creates_worktree_and_launches(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_spawn_workdir_blocking must create worktree and call Popen with kitty."""
    from zeus.dashboard.app import ZeusApp

    zeus_home = str(tmp_path / "zeus")
    os.makedirs(zeus_home, exist_ok=True)
    (Path(zeus_home) / "workdir-agent.md").write_text("prompt for <agent_name>")
    monkeypatch.setenv("ZEUS_HOME", zeus_home)

    # Mock Popen so we don't actually launch kitty — but let subprocess.run through
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    real_popen = subprocess.Popen
    mock_popen = MagicMock(return_value=mock_proc)

    def selective_popen(cmd, **kwargs):
        if cmd and cmd[0] == "kitty":
            return mock_popen(cmd, **kwargs)
        return real_popen(cmd, **kwargs)

    monkeypatch.setattr("subprocess.Popen", selective_popen)

    # Mock enqueue_envelope
    mock_enqueue = MagicMock()
    monkeypatch.setattr("zeus.dashboard.app.enqueue_envelope", mock_enqueue)

    agent = MagicMock()
    agent.cwd = git_repo
    agent.agent_id = "parent-id-123"
    agent.workspace = ""

    app = ZeusApp.__new__(ZeusApp)
    result = app._spawn_workdir_blocking(agent, "test-agent")

    assert result is True

    # Worktree was created
    wt = worktree_path(git_repo, "test-agent")
    assert os.path.isdir(wt)
    assert get_current_branch(wt) == "zeus/test-agent"

    # Kitty was called with correct cwd and --session (same as NewAgentScreen)
    assert mock_popen.called
    call_args = mock_popen.call_args
    cmd = call_args[0][0]  # positional arg 0
    assert cmd[0] == "kitty"
    assert "--directory" in cmd
    dir_idx = cmd.index("--directory")
    assert cmd[dir_idx + 1] == wt
    bash_cmd = cmd[-1]
    assert "pi --session" in bash_cmd

    # Env vars set (same as NewAgentScreen)
    env = call_args[1]["env"]
    assert env["ZEUS_AGENT_NAME"] == "test-agent"
    assert env["ZEUS_ROLE"] == "hippeus"
    assert env["ZEUS_PARENT_BRANCH"] == "main"
    assert env["ZEUS_PARENT_ID"] == "parent-id-123"
    assert "ZEUS_SESSION_PATH" in env

    # Workdir prompt enqueued via message queue
    assert mock_enqueue.called
    envelope = mock_enqueue.call_args[0][0]
    assert envelope.target_agent_id == env["ZEUS_AGENT_ID"]
    assert envelope.target_name == "test-agent"

    # Cleanup
    remove_worktree(git_repo, "test-agent")


def test_check_worktree_merge_done_cleans_up(
    git_repo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_check_worktree_merge_done must remove worktree and kill agent on signal."""
    import json
    from zeus.dashboard.app import ZeusApp

    # Create a worktree to clean up
    create_worktree(git_repo, "done-agent", base_branch="main")
    wt = worktree_path(git_repo, "done-agent")
    assert os.path.isdir(wt)

    # Set up bus inbox with a merge_done signal
    bus_dir = tmp_path / "agent-bus" / "inbox" / "zeus" / "new"
    bus_dir.mkdir(parents=True)
    signal_file = bus_dir / "worktree-done-test.json"
    signal_file.write_text(json.dumps({
        "type": "worktree_merge_done",
        "agent_id": "abc123",
        "agent_name": "done-agent",
        "repo_root": git_repo,
    }))

    # Patch AGENT_BUS_INBOX_DIR in config module (imported inside the method)
    monkeypatch.setattr("zeus.config.AGENT_BUS_INBOX_DIR", tmp_path / "agent-bus" / "inbox")

    # Mock the app enough
    app = ZeusApp.__new__(ZeusApp)
    app._agent_windows = []  # no matching agent — just test worktree cleanup
    app.notify = MagicMock()

    app._check_worktree_merge_done()

    # Signal file removed
    assert not signal_file.exists()

    # Worktree cleaned up
    assert not os.path.isdir(wt)

    # Notification fired
    assert app.notify.called
    call_args = app.notify.call_args
    assert "done-agent" in str(call_args)
