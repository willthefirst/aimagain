"""Tests for scripts/session_start_branch_check.py.

The hook is purely informational — these tests pin the output shape so the
warning about being on `main` (and the stash/dirty-state surfacing) doesn't
silently disappear from the agent's first impression.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "session_start_branch_check.py"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "gpg.format", "openpgp")
    (repo / "pyproject.toml").write_text("[project]\nname='t'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    return repo


def _run_in(repo: Path) -> subprocess.CompletedProcess:
    # The hook resolves repo root by going parent.parent from its own path, so
    # we invoke it with cwd=repo and rely on its internal chdir for the rest.
    return subprocess.run(
        ["python", str(HOOK)],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
    )


def _install_hook(repo: Path) -> Path:
    fake_scripts = repo / "scripts"
    fake_scripts.mkdir()
    copy = fake_scripts / "session_start_branch_check.py"
    copy.write_text(HOOK.read_text())
    copy.chmod(0o755)
    _git(repo, "add", "scripts/session_start_branch_check.py")
    _git(repo, "commit", "-m", "install hook")
    return copy


def test_prints_branch_and_clean_state_on_feature_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)
    _git(repo, "checkout", "-b", "fix/123-foo")

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "branch: fix/123-foo" in result.stderr
    assert "clean working tree" in result.stderr
    assert "trunk branch" not in result.stderr


def test_warns_loudly_on_main_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "branch: main" in result.stderr
    assert "trunk branch" in result.stderr
    assert "git worktree add" in result.stderr


def test_auto_pulls_on_clean_main_with_remote(tmp_path: Path) -> None:
    # Set up a bare remote + a clone so the working repo has a tracking branch.
    bare = tmp_path / "bare.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(bare)],
        check=True,
        capture_output=True,
    )

    repo = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "pyproject.toml").write_text("[project]\nname='t'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "init")
    _git(repo, "push", "origin", "main")

    copy = _install_hook(repo)

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "⚡" in result.stderr
    assert "pulling latest" in result.stderr.lower()


def test_skips_auto_pull_on_clean_main_without_remote(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "⚡" not in result.stderr


def test_skips_auto_pull_on_dirty_main(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)
    (repo / "dirty.txt").write_text("dirty")

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "⚡" not in result.stderr
    assert "file(s) modified" in result.stderr


def test_skips_auto_pull_on_feature_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)
    _git(repo, "checkout", "-b", "fix/123-something")

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "⚡" not in result.stderr


def test_surfaces_dirty_state_and_stashes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    copy = _install_hook(repo)
    _git(repo, "checkout", "-b", "fix/999")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "stash", "push", "-u", "-m", "wip-from-prior-session")

    # Leave one untracked file so dirty-state surfacing fires.
    (repo / "c.txt").write_text("c")

    result = subprocess.run(
        [sys.executable, str(copy)], capture_output=True, text=True, cwd=repo
    )
    assert result.returncode == 0
    assert "file(s) modified" in result.stderr
    assert "stash:" in result.stderr
    assert "prior-session" in result.stderr
