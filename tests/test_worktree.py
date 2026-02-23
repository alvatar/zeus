"""Tests for zeus.worktree — git worktree helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from zeus.worktree import (
    create_worktree,
    get_current_branch,
    get_repo_root,
    remove_worktree,
    worktree_branch,
    worktree_path,
    worktree_base_dir,
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
