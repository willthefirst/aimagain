"""Tests for `dev worktree {add,gc}` in scripts/dev_cli.py.

The commands shell out to `git worktree`. Tests build a real git
repository in `tmp_path`, point a `CLIRunner`-shaped object at it, and
assert on filesystem + branch state. Subprocess invocation is the
contract we care about — there's nothing useful to mock here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import WorktreeCommands


class _FakeRunner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        return subprocess.run(cmd, cwd=cwd or self.project_root, check=False).returncode


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "pyproject.toml").write_text("[project]\nname='t'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    # Stand in for `origin/main` without spinning up a remote: just track
    # a local-only ref. `git worktree add` accepts any ref, and the GC
    # path's "merged into origin/main" check is exercised via a real
    # remote in the GC test.
    _git(repo, "branch", "-f", "origin/main", "main")
    return repo


def test_add_creates_worktree_with_issue_named_directory(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    rc = cmd.add("707", base="origin/main")
    assert rc == 0
    expected = repo / ".claude" / "worktrees" / "issue-707"
    assert expected.is_dir()
    # And the new branch exists with the expected name.
    branches = subprocess.run(
        ["git", "branch", "--list", "fix/707"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "fix/707" in branches


def test_add_slugifies_descriptive_name(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    rc = cmd.add("Issue 707: Verification Badge!", base="origin/main")
    assert rc == 0
    expected = repo / ".claude" / "worktrees" / "issue-707-verification-badge"
    assert expected.is_dir()


def test_add_refuses_uuid_shaped_names(tmp_path: Path, capsys) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    rc = cmd.add("a3f9c2deadbeef", base="origin/main")
    assert rc == 2
    out = capsys.readouterr().out
    assert "opaque name" in out
    # Nothing was created on disk.
    assert not (repo / ".claude" / "worktrees" / "a3f9c2deadbeef").exists()


def test_add_refuses_when_path_exists(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    assert cmd.add("707", base="origin/main") == 0
    # Second invocation collides.
    assert cmd.add("707", base="origin/main") == 1


def test_gc_previews_without_yes_flag(tmp_path: Path, capsys) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    assert cmd.add("707", base="origin/main") == 0
    # `fix/707` was branched from `origin/main` with no divergence, so
    # git considers it merged. Without --yes, gc should preview only.
    rc = cmd.gc(assume_yes=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Pass --yes" in out
    assert (repo / ".claude" / "worktrees" / "issue-707").exists()


def test_gc_removes_merged_worktrees_with_yes_flag(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    assert cmd.add("707", base="origin/main") == 0
    worktree = repo / ".claude" / "worktrees" / "issue-707"
    assert worktree.exists()
    rc = cmd.gc(assume_yes=True)
    assert rc == 0
    assert not worktree.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", "fix/707"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "fix/707" not in branches


def test_gc_leaves_unmerged_worktrees_alone(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    assert cmd.add("707", base="origin/main") == 0
    worktree = repo / ".claude" / "worktrees" / "issue-707"
    # Add a divergent commit on fix/707 so it's no longer "merged".
    (worktree / "newfile").write_text("x")
    _git(worktree, "add", "newfile")
    _git(worktree, "commit", "-m", "diverge")
    rc = cmd.gc(assume_yes=True)
    assert rc == 0
    assert worktree.exists()  # still there


def test_gc_never_removes_the_main_checkout(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    cmd = WorktreeCommands(_FakeRunner(repo))
    # Even if main is in the merged set, the main checkout must not be GC'd.
    rc = cmd.gc(assume_yes=True)
    assert rc == 0
    assert (repo / ".git").exists()
    assert (repo / "pyproject.toml").exists()
