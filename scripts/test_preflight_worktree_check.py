"""Tests for the PreToolUse preflight worktree-check hook.

Each test sets up a temp git repo (or worktree off one), pipes a synthetic
Claude Code hook payload to the script, and asserts the exit code matches
the "Allow vs block matrix" documented in `preflight_worktree_check.py`:

  main checkout, branch=main         → BLOCK (exit 2)
  main checkout, branch=feature      → ALLOW (exit 0)
  worktree (any branch)              → ALLOW (exit 0)

Non-guarded tools (e.g. Bash, Read) always allow regardless of CWD/branch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "preflight_worktree_check.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_main_checkout(root: Path) -> Path:
    """Create a fresh repo at ``root`` with one commit on `main`."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("seed\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _run_hook(cwd: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _edit_payload(cwd: Path, file_path: str = "/tmp/x.py") -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
        "cwd": str(cwd),
    }


def test_blocks_in_main_checkout_on_main_branch(tmp_path: Path) -> None:
    """The combination the project rule actually cares about: main
    checkout + on main = the shared working tree where two agents would
    clobber each other. Hook must refuse with exit 2 and the human-
    readable instructions on stderr."""
    repo = _init_main_checkout(tmp_path / "repo")
    result = _run_hook(repo, _edit_payload(repo))
    assert result.returncode == 2, result.stderr
    assert "BLOCKED" in result.stderr
    assert "dev worktree add" in result.stderr


def test_allows_in_main_checkout_on_feature_branch(tmp_path: Path) -> None:
    """In-flight feature work on the main checkout is allowed — the rule
    is about *new* work starting from a clean main, not blocking every
    edit. Switching to a feature branch (`git checkout <branch>`) is the
    documented escape hatch the BLOCKED message mentions."""
    repo = _init_main_checkout(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "fix/some-feature")
    result = _run_hook(repo, _edit_payload(repo))
    assert result.returncode == 0, result.stderr


def test_allows_in_worktree(tmp_path: Path) -> None:
    """The desired state — work in a linked worktree branched off main —
    must always allow. Detection is via ``git rev-parse --git-dir`` vs
    ``--git-common-dir``; the test pins that the comparison resolves
    correctly for a real ``git worktree add`` layout (not a hand-faked
    directory structure)."""
    repo = _init_main_checkout(tmp_path / "repo")
    worktree = tmp_path / "worktrees" / "feature"
    _git(repo, "worktree", "add", "-b", "fix/feature-x", str(worktree))
    result = _run_hook(worktree, _edit_payload(worktree))
    assert result.returncode == 0, result.stderr


def test_allows_non_guarded_tools(tmp_path: Path) -> None:
    """Bash / Read / Grep / etc. are not guarded — the rule is specifically
    about file-modifying tools. A Bash call from main-on-main must pass
    through (otherwise the agent couldn't even run ``dev worktree add``
    to escape the block)."""
    repo = _init_main_checkout(tmp_path / "repo")
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "cwd": str(repo),
    }
    result = _run_hook(repo, payload)
    assert result.returncode == 0, result.stderr


def test_allows_when_payload_is_empty(tmp_path: Path) -> None:
    """Robustness: a malformed / empty stdin must never wedge edits.
    The hook's job is enforcement of one specific rule, not validation
    of the harness payload — fail open on anything unparseable."""
    repo = _init_main_checkout(tmp_path / "repo")
    result = subprocess.run(
        [str(HOOK)], input="", cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("tool", ["Edit", "Write", "NotebookEdit"])
def test_all_guarded_tools_are_blocked(tool: str, tmp_path: Path) -> None:
    """Every tool the GUARDED_TOOLS constant lists must hit the block
    path under main-on-main, not just Edit. Parametrize so a future
    refactor that drops a tool from the matcher gets caught here."""
    repo = _init_main_checkout(tmp_path / "repo")
    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": "/tmp/x"},
        "cwd": str(repo),
    }
    result = _run_hook(repo, payload)
    assert result.returncode == 2, result.stderr


def test_allows_when_file_path_is_inside_worktree_even_if_cwd_is_main(
    tmp_path: Path,
) -> None:
    """EnterWorktree switches the session into a linked worktree but the
    harness payload ``cwd`` may still report the main checkout. The hook
    must allow the write when the *target file* lives inside a worktree,
    even when ``cwd`` would otherwise trigger a block.

    This is the bug fixed by the _path_in_worktree fallback: previously,
    Edit/Write calls after EnterWorktree were erroneously blocked because
    the hook only checked cwd, not file_path."""
    repo = _init_main_checkout(tmp_path / "repo")
    worktree = tmp_path / "worktrees" / "feature"
    _git(repo, "worktree", "add", "-b", "fix/feature-y", str(worktree))

    # Payload simulates what the harness sends after EnterWorktree:
    # cwd is still the main checkout, but file_path is inside the worktree.
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(worktree / "src" / "foo.py")},
        "cwd": str(repo),  # main checkout — the stale harness cwd
    }
    result = _run_hook(repo, payload)
    assert result.returncode == 0, result.stderr
