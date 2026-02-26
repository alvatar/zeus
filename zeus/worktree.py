"""Git worktree helpers for Workdir Hippeus agents."""

from __future__ import annotations

import os
import re
import shutil
import subprocess


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


def _run_git_capture(
    cwd: str,
    args: list[str],
    *,
    timeout: int = 15,
) -> tuple[bool, str]:
    """Run a git command and return (ok, stdout_or_error)."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, str(exc)

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        if err:
            return False, err
        return False, f"git {' '.join(args)} failed (exit {result.returncode})"

    return True, (result.stdout or "").strip()


def _normalize_branch_name(raw: str) -> str:
    candidate = raw.strip().strip("\"'")
    if candidate.startswith("refs/heads/"):
        candidate = candidate.removeprefix("refs/heads/")
    if candidate.startswith("origin/"):
        candidate = candidate.removeprefix("origin/")
    return candidate.strip()


def _branch_exists(cwd: str, branch: str) -> bool:
    if not branch:
        return False
    ok, _ = _run_git_capture(
        cwd,
        ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        timeout=5,
    )
    return ok


def _infer_review_base_branch(cwd: str, branch: str) -> str:
    """Best-effort base branch detection for worktree review."""
    ok, reflog = _run_git_capture(
        cwd,
        ["reflog", "show", "--format=%gs", "-n", "30", branch],
        timeout=10,
    )
    if ok and reflog:
        for line in reflog.splitlines():
            match = re.match(r"^branch: Created from (.+)$", line.strip())
            if not match:
                continue
            candidate = _normalize_branch_name(match.group(1))
            if not candidate or candidate in {"HEAD", branch}:
                continue
            if _branch_exists(cwd, candidate):
                return candidate

    ok, upstream = _run_git_capture(
        cwd,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        timeout=5,
    )
    if ok and upstream:
        candidate = _normalize_branch_name(upstream)
        if candidate and candidate != branch and _branch_exists(cwd, candidate):
            return candidate

    for fallback in ("main", "master"):
        if fallback != branch and _branch_exists(cwd, fallback):
            return fallback

    return ""


def _append_review_footer(content: str) -> str:
    body = (content or "").rstrip("\n")
    if not body:
        return "=== END OF REVIEW ===\n"
    return f"{body}\n\n=== END OF REVIEW ===\n"


def build_worktree_review(
    cwd: str,
    *,
    base_branch: str = "",
    use_delta: bool = True,
    delta_width: int | None = None,
    delta_theme_mode: str = "dark",
) -> tuple[bool, str]:
    """Build a single continuous review view for a worktree branch.

    Review semantics:
    - Commit list: base..branch
    - Diff: base...branch (merge-base style / PR-style)
    - Uncommitted changes are intentionally excluded from the diff.
    - Delta width can be forced via ``delta_width`` to match UI viewport.
    - Delta color mode can be forced via ``delta_theme_mode`` ("dark" | "light").
    """
    repo_root = get_repo_root(cwd)
    if not repo_root:
        return False, "Not a git repository."

    ok, git_dir = _run_git_capture(cwd, ["rev-parse", "--git-dir"], timeout=5)
    if not ok:
        return False, f"Cannot determine git dir: {git_dir}"

    ok, git_common = _run_git_capture(cwd, ["rev-parse", "--git-common-dir"], timeout=5)
    if not ok:
        return False, f"Cannot determine git common dir: {git_common}"

    if git_dir == git_common or git_dir == ".git":
        return False, "Selected target is not a git worktree checkout."

    branch = get_current_branch(cwd)
    if not branch or branch == "HEAD":
        return False, "Cannot determine current branch for worktree review."

    resolved_base = _normalize_branch_name(base_branch) if base_branch else ""
    if resolved_base and not _branch_exists(cwd, resolved_base):
        return False, f"Base branch '{resolved_base}' does not exist in this repository."
    if not resolved_base:
        resolved_base = _infer_review_base_branch(cwd, branch)
    if not resolved_base:
        return False, "Cannot infer a base branch (expected main/master or branch creation metadata)."
    if resolved_base == branch:
        return False, "Base branch resolves to current branch; cannot build review."

    ok, merge_base = _run_git_capture(cwd, ["merge-base", resolved_base, branch], timeout=10)
    if not ok:
        return False, f"Cannot compute merge-base for {resolved_base} and {branch}: {merge_base}"

    ok, head = _run_git_capture(cwd, ["rev-parse", "HEAD"], timeout=5)
    if not ok:
        return False, f"Cannot resolve HEAD: {head}"

    ok, status = _run_git_capture(cwd, ["status", "--porcelain"], timeout=10)
    if not ok:
        return False, f"Cannot read git status: {status}"
    dirty = bool(status.strip())

    ok, commits = _run_git_capture(
        cwd,
        ["--no-pager", "log", "--graph", "--decorate", "--oneline", f"{resolved_base}..{branch}"],
        timeout=20,
    )
    if not ok:
        return False, f"Cannot build commit summary: {commits}"
    if not commits.strip():
        commits = "(no commits ahead of base)"

    ok, diff_stat = _run_git_capture(
        cwd,
        ["--no-pager", "diff", "--stat", "--summary", f"{resolved_base}...{branch}"],
        timeout=20,
    )
    if not ok:
        return False, f"Cannot build diff stat: {diff_stat}"
    if not diff_stat.strip():
        diff_stat = "(no file-level changes)"

    ok, name_status = _run_git_capture(
        cwd,
        ["--no-pager", "diff", "--name-status", f"{resolved_base}...{branch}"],
        timeout=20,
    )
    if not ok:
        return False, f"Cannot build name-status summary: {name_status}"
    if not name_status.strip():
        name_status = "(no changed paths)"

    ok, full_diff = _run_git_capture(
        cwd,
        [
            "--no-pager",
            "diff",
            "--find-renames",
            "--find-copies-harder",
            "--submodule=diff",
            f"{resolved_base}...{branch}",
        ],
        timeout=120,
    )
    if not ok:
        return False, f"Cannot build full diff: {full_diff}"
    if not full_diff.strip():
        full_diff = "(no diff between merge-base and branch head)"

    header_lines = [
        "=== WORKTREE REVIEW ===",
        f"repo: {repo_root}",
        f"worktree: {cwd}",
        f"base: {resolved_base}",
        f"branch: {branch}",
        f"merge-base: {merge_base}",
        f"head: {head}",
        f"ranges: commits={resolved_base}..{branch} diff={resolved_base}...{branch}",
    ]
    if dirty:
        header_lines.append(
            "warning: worktree has uncommitted changes; they are excluded from this review"
        )

    plain = (
        "\n".join(header_lines)
        + "\n\n=== COMMITS (base..branch) ===\n"
        + commits
        + "\n\n=== FILE SUMMARY (base...branch) ===\n"
        + diff_stat
        + "\n\n=== PATH STATUS (base...branch) ===\n"
        + name_status
        + "\n\n=== FULL DIFF (base...branch) ===\n"
        + full_diff
        + "\n"
    )

    if use_delta and shutil.which("delta"):
        try:
            # Keep split layout deterministic regardless of user/global config.
            # For now, light review mode reuses the same delta rendering as dark
            # mode; only the surrounding TUI background changes.
            delta_cmd = ["delta", "--paging=never", "--side-by-side", "--dark"]
            # Neutralize divider lines/bars to gray.
            delta_cmd.extend([
                "--file-decoration-style",
                "#5a5a5a",
                "--hunk-header-decoration-style",
                "#5a5a5a",
                "--line-numbers-left-style",
                "#5a5a5a",
                "--line-numbers-right-style",
                "#5a5a5a",
            ])

            width = int(delta_width or 0)
            if width > 0:
                delta_cmd.append(f"--width={max(40, width)}")

            delta_result = subprocess.run(
                delta_cmd,
                input=plain,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=cwd,
            )
            if delta_result.returncode == 0 and (delta_result.stdout or "").strip():
                return True, _append_review_footer(delta_result.stdout)

            detail = (delta_result.stderr or delta_result.stdout or "").strip()
            fallback = plain
            if detail:
                fallback += f"\n[delta warning] {detail}\n"
            return True, _append_review_footer(fallback)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return True, _append_review_footer(
                plain + f"\n[delta warning] {exc}\n"
            )

    return True, _append_review_footer(plain)
