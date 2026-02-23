# Workdir Hippeus — <agent_name>

You are working in a **git worktree** — an isolated working directory branched from `<parent_branch>`. Your branch is `<branch_name>`.

## What this means

- Your working directory (`<worktree_path>`) is a separate checkout of the same repository.
- You share git history with the main repo at `<repo_root>`, but your changes are isolated on your branch.
- The parent agent and other agents working in the main repo **cannot see your changes** until you merge.
- You **cannot step on their files**, and they cannot step on yours.

## Workflow

1. **Work normally.** Edit files, run tests, commit. Everything stays on your branch `<branch_name>`.
2. **Commit frequently.** Each logical change should be a commit on your branch.
3. **When your task is complete**, merge your branch back:
   - Use the `zeus_worktree_merge` tool. It will attempt to merge your branch into `<parent_branch>`.
   - If the merge is clean, you're done.
   - If there are conflicts, the tool will report them. Read the conflicted files, resolve them, `git add` the resolved files, and run `git commit` to complete the merge. Then call `zeus_worktree_merge` again to verify.
4. After a successful merge, report completion to the user.

## Rules

- Do NOT checkout other branches in this worktree.
- Do NOT modify files outside your worktree path.
- Do NOT run `git worktree remove` yourself — Zeus handles cleanup.
- Commit your work before attempting to merge.
