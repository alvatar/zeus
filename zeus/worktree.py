"""Git worktree helpers for Workdir Hippeus agents."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


_WORKTREE_DIR = ".worktrees"
_BRANCH_PREFIX = "zeus/"


def worktree_base_dir(repo_root: str) -> str:
    """Return the .worktrees directory inside the repo."""
    return os.path.join(repo_root, _WORKTREE_DIR)


def worktree_path(repo_root: str, agent_name: str) -> str:
    """Return the full path for a worktree checkout."""
    return os.path.join(worktree_base_dir(repo_root), agent_name)


def worktree_branch(agent_name: str) -> str:
    """Return the branch name for a workdir agent."""
    return f"{_BRANCH_PREFIX}{agent_name}"


def get_repo_root(cwd: str) -> str:
    """Return the git repo root for a directory, or empty string."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def get_current_branch(cwd: str) -> str:
    """Return the current branch name, or empty string."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _ensure_gitignore_entry(repo_root: str) -> None:
    """Add .worktrees to .gitignore if not already there."""
    gitignore = os.path.join(repo_root, ".gitignore")
    entry = f"/{_WORKTREE_DIR}/"
    try:
        existing = ""
        if os.path.exists(gitignore):
            with open(gitignore) as f:
                existing = f.read()
        if entry not in existing and _WORKTREE_DIR not in existing:
            with open(gitignore, "a") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"{entry}\n")
    except OSError:
        pass


def create_worktree(
    repo_root: str,
    agent_name: str,
    *,
    base_branch: str = "",
) -> tuple[bool, str]:
    """Create a git worktree + branch for a workdir agent.

    Returns (success, message). On success, message is the worktree path.
    On failure, message is the error.
    """
    wt_path = worktree_path(repo_root, agent_name)
    branch = worktree_branch(agent_name)

    if os.path.exists(wt_path):
        return False, f"Worktree path already exists: {wt_path}"

    # Ensure .worktrees/ in .gitignore
    _ensure_gitignore_entry(repo_root)

    # Create parent dir
    os.makedirs(worktree_base_dir(repo_root), exist_ok=True)

    # Create worktree with new branch from current HEAD (or base_branch)
    cmd = ["git", "worktree", "add", "-b", branch, wt_path]
    if base_branch:
        cmd.append(base_branch)

    try:
        r = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30, cwd=repo_root,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            return False, f"git worktree add failed: {err}"
        return True, wt_path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"git worktree add error: {exc}"


def remove_worktree(repo_root: str, agent_name: str) -> tuple[bool, str]:
    """Remove a worktree and delete its branch.

    Returns (success, message).
    """
    wt_path = worktree_path(repo_root, agent_name)
    branch = worktree_branch(agent_name)
    errors: list[str] = []

    # Remove worktree
    try:
        r = subprocess.run(
            ["git", "worktree", "remove", "--force", wt_path],
            capture_output=True, text=True, timeout=15, cwd=repo_root,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            errors.append(f"worktree remove: {err}")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        errors.append(f"worktree remove: {exc}")

    # Delete branch (force — worktree is gone)
    try:
        r = subprocess.run(
            ["git", "branch", "-D", branch],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            # Branch might not exist if creation failed partway
            if "not found" not in err.lower():
                errors.append(f"branch delete: {err}")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        errors.append(f"branch delete: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, f"Removed worktree and branch for {agent_name}"


def merge_worktree_branch(
    repo_root: str,
    agent_name: str,
    *,
    target_branch: str = "",
) -> tuple[bool, str]:
    """Merge the workdir agent's branch into the target branch.

    Runs from the MAIN repo (not the worktree) to avoid worktree branch
    checkout conflicts. Uses `git merge --no-ff` for clear history.

    Returns (success, message). On conflict, success=False and message
    contains the conflict details.
    """
    branch = worktree_branch(agent_name)

    if not target_branch:
        target_branch = get_current_branch(repo_root)
    if not target_branch:
        return False, "Cannot determine target branch"

    # Ensure we're on the target branch in the main repo
    try:
        r = subprocess.run(
            ["git", "checkout", target_branch],
            capture_output=True, text=True, timeout=15, cwd=repo_root,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            return False, f"Cannot checkout {target_branch}: {err}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"Checkout error: {exc}"

    # Attempt merge
    try:
        r = subprocess.run(
            ["git", "merge", "--no-ff", branch, "-m", f"Merge {branch} into {target_branch}"],
            capture_output=True, text=True, timeout=60, cwd=repo_root,
        )
        if r.returncode == 0:
            return True, (r.stdout or "").strip() or "Merge successful"

        # Merge failed — likely conflicts
        output = (r.stdout or "") + "\n" + (r.stderr or "")

        # Get list of conflicted files
        try:
            diff_r = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                capture_output=True, text=True, timeout=10, cwd=repo_root,
            )
            conflicts = diff_r.stdout.strip()
        except Exception:
            conflicts = ""

        # Abort the merge to leave repo clean
        try:
            subprocess.run(
                ["git", "merge", "--abort"],
                capture_output=True, timeout=10, cwd=repo_root,
            )
        except Exception:
            pass

        msg = f"Merge conflicts detected.\n{output.strip()}"
        if conflicts:
            msg += f"\n\nConflicted files:\n{conflicts}"
        return False, msg

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        # Try to abort if we started a merge
        try:
            subprocess.run(
                ["git", "merge", "--abort"],
                capture_output=True, timeout=10, cwd=repo_root,
            )
        except Exception:
            pass
        return False, f"Merge error: {exc}"
