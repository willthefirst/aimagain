#!/usr/bin/env python3
"""PreToolUse hook: refuse Edit/Write/NotebookEdit on the main checkout's main
branch.

Multi-agent sessions in this repo share one working tree (CLAUDE.md flags this
explicitly). The convention is: every new task starts on a worktree branched
off main via ``dev worktree add <slug>``. This hook is the enforcement leg of
that convention — the SessionStart hook warns; this one blocks.

Allow vs block matrix:

  main checkout, branch=main         → BLOCK (this is the case we're stopping)
  main checkout, branch=feature      → ALLOW (already on a feature branch;
                                       likely an in-flight session continuing)
  worktree (any branch)              → ALLOW (the desired state)

Worktree detection: ``git rev-parse --git-dir`` differs from
``git rev-parse --git-common-dir`` inside a worktree (the per-worktree git dir
sits under ``<main>/.git/worktrees/<name>`` while ``--git-common-dir`` returns
the shared ``<main>/.git``). In the main checkout the two are equal.

The check runs twice:

  1. Against the payload ``cwd`` — the session's reported working directory.
  2. Against the target ``file_path`` — needed because the harness ``cwd``
     may still point at the main checkout even after ``EnterWorktree`` has
     switched the session into a linked worktree. If the file being written
     lives inside a worktree, that's sufficient evidence to allow it.

Exits 2 with a stderr message on block (Claude Code surfaces stderr to the
model so the next step is actionable). Exits 0 (allow) on every other path
and on any internal failure — the hook must not wedge the session if git
behaves unexpectedly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

GUARDED_TOOLS = {"Edit", "Write", "NotebookEdit"}


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip()
    except FileNotFoundError:
        return ""


def _in_worktree() -> bool:
    """True if the CWD is inside a linked worktree (not the main checkout)."""
    git_dir = _git(["rev-parse", "--git-dir"])
    common_dir = _git(["rev-parse", "--git-common-dir"])
    if not git_dir or not common_dir:
        return False
    # Normalize: --git-dir is relative when CWD is the worktree root, absolute
    # when CWD is deeper. Resolve both to absolute paths before comparing.
    git_abs = (Path.cwd() / git_dir).resolve()
    common_abs = (Path.cwd() / common_dir).resolve()
    return git_abs != common_abs


def _path_in_worktree(file_path: str) -> bool:
    """True if file_path (or its nearest existing ancestor) is inside a linked worktree.

    Used as a fallback when the harness ``cwd`` lags behind an ``EnterWorktree``
    call — the payload cwd may still point at the main checkout while the target
    file already lives in the worktree.
    """
    if not file_path:
        return False
    p = Path(file_path).resolve()
    # Walk up to the nearest existing directory; the file itself may not exist yet.
    while not p.exists():
        parent = p.parent
        if parent == p:
            return False  # reached filesystem root without finding anything
        p = parent
    check_dir = p if p.is_dir() else p.parent
    old_cwd = Path.cwd()
    try:
        os.chdir(check_dir)
        return _in_worktree()
    except OSError:
        return False
    finally:
        try:
            os.chdir(old_cwd)
        except OSError:
            pass


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in GUARDED_TOOLS:
        return 0

    file_path = payload.get("tool_input", {}).get("file_path", "")

    # Move to the cwd Claude Code reports — the hook process inherits its own
    # cwd from the harness, which is not necessarily the session's cwd.
    cwd = payload.get("cwd") or os.getcwd()
    try:
        os.chdir(cwd)
    except OSError:
        return 0

    if _in_worktree():
        return 0

    # The harness cwd may not reflect an EnterWorktree switch — also check
    # whether the target file itself lives inside a worktree.
    if _path_in_worktree(file_path):
        return 0

    branch = _git(["branch", "--show-current"])
    if branch not in {"main", "master"}:
        return 0

    # Pick a slug hint from the file being edited so the suggested command
    # is concrete. Fallback to "task" so the message stays valid.
    slug_hint = "task"
    if file_path:
        parts = [p for p in Path(file_path).parts if p not in {"/", ".", ".."}]
        if parts:
            slug_hint = parts[-1].split(".")[0] or "task"

    print(
        "\n".join(
            [
                "[preflight-worktree-check] BLOCKED.",
                "",
                f"  You're in the main checkout on `{branch}` — this is the shared",
                "  working tree. New work must start on a worktree branched off main.",
                "",
                "  Create one and re-attempt the edit from there:",
                "",
                f"      dev worktree add {slug_hint}",
                "",
                "  Then `cd` into the printed path (under `.claude/worktrees/...`)",
                "  before retrying the Edit / Write / NotebookEdit call.",
                "",
                "  If this is a quick in-place fix on an existing feature branch,",
                "  switch to that branch (`git checkout <branch>`) and retry — the",
                "  hook only blocks the main-checkout-on-main combination.",
            ]
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
