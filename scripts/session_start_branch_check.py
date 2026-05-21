#!/usr/bin/env python3
"""SessionStart hook: print real branch + warn loudly on main/master.

Multi-agent sessions in this repo share `/home/user/bedlam-connect`, and the
harness-provided "Current branch:" line has been observed lying when another
agent flipped HEAD between sessions. This hook is the first thing the agent
sees: it states what `git` itself says, surfaces dirty state and prior-session
stashes, and recommends moving to a worktree if we're on main.

The hook never fails (always exits 0). Its job is visibility, not enforcement.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.rstrip("\n")
    except FileNotFoundError:
        return ""


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)

    branch = _git(["branch", "--show-current"]) or "(detached HEAD)"
    status = _git(["status", "--short", "--branch"])
    stashes = _git(["stash", "list"])

    lines: list[str] = ["[session-start branch check]"]
    lines.append(f"  cwd:    {Path.cwd()}")
    lines.append(f"  branch: {branch}")

    status_lines = [s for s in status.splitlines() if s and not s.startswith("##")]
    if status_lines:
        truncated = status_lines[:10]
        lines.append(f"  dirty:  {len(status_lines)} file(s) modified")
        for s in truncated:
            lines.append(f"          {s}")
        if len(status_lines) > len(truncated):
            lines.append(f"          ... and {len(status_lines) - len(truncated)} more")
    else:
        lines.append("  dirty:  clean working tree")

    if stashes:
        stash_count = len(stashes.splitlines())
        lines.append(
            f"  stash:  {stash_count} entry(ies) — prior-session work may be hiding here"
        )
        lines.append("          run `git stash list` to inspect")

    if branch in {"main", "master"}:
        lines.append("")
        lines.append("  ⚠ You are on the trunk branch in the shared working tree.")
        lines.append(
            "    Other agents may flip HEAD under you. Move to a worktree before editing:"
        )
        lines.append(
            "        git worktree add .claude/worktrees/<issue-name> -b fix/<N>-<slug> origin/main"
        )

    print("\n".join(lines), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
