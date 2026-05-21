"""Tests for the per-worktree COMPOSE_PROJECT_NAME plumbing (#748).

`docker compose` is namespaced by `COMPOSE_PROJECT_NAME`. Without it,
two worktrees that both try to `dev up` collide on container/volume/
network names, and `dev seed` invoked from a worktree silently leaks
into the main checkout's volume. The CLIRunner now derives a project
name from the project-root directory and injects it into every
subprocess.run env.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.dev_cli import CLIRunner


def _make_runner_at(root: Path) -> CLIRunner:
    # CLIRunner.__init__ resolves project_root by walking up from cwd to
    # the first pyproject.toml. We construct the runner then override
    # project_root so we can exercise different worktree paths without
    # chdir tricks.
    runner = CLIRunner.__new__(CLIRunner)
    runner.project_root = root
    runner.compose_project_name = runner._derive_compose_project_name()
    return runner


def test_main_checkout_yields_bedlam_named_project():
    # Project root is `bedlam-connect`; the slug already starts with
    # `bedlam`, so we don't double-prefix.
    runner = _make_runner_at(Path("/home/user/bedlam-connect"))
    assert runner.compose_project_name == "bedlam-connect"


def test_worktree_directory_yields_unique_name():
    runner = _make_runner_at(
        Path("/home/user/bedlam-connect/.claude/worktrees/issue-707-foo")
    )
    assert runner.compose_project_name == "bedlam-issue-707-foo"


def test_two_worktrees_yield_distinct_names():
    a = _make_runner_at(Path("/x/.claude/worktrees/issue-707-foo"))
    b = _make_runner_at(Path("/x/.claude/worktrees/issue-708-bar"))
    assert a.compose_project_name != b.compose_project_name


def test_compose_env_injects_project_name():
    runner = _make_runner_at(Path("/x/.claude/worktrees/issue-707-foo"))
    env = runner._compose_env()
    assert env.get("COMPOSE_PROJECT_NAME") == "bedlam-issue-707-foo"


def test_compose_env_respects_user_override(monkeypatch):
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "user-pick")
    runner = _make_runner_at(Path("/x/.claude/worktrees/issue-707-foo"))
    env = runner._compose_env()
    # User's choice wins — we never silently rewrite a value they set.
    assert env["COMPOSE_PROJECT_NAME"] == "user-pick"


def test_is_compose_cmd_recognises_docker_compose_invocations():
    runner = _make_runner_at(Path("/x"))
    assert runner._is_compose_cmd(["docker", "compose", "-f", "x.yml", "up"])
    assert runner._is_compose_cmd(["docker-compose", "up"])
    # Not compose:
    assert not runner._is_compose_cmd(["pytest", "-v"])
    assert not runner._is_compose_cmd(["alembic", "upgrade", "head"])
    assert not runner._is_compose_cmd(["docker", "build", "."])
    assert not runner._is_compose_cmd(["docker", "ps"])
    assert not runner._is_compose_cmd(["git", "status"])
    assert not runner._is_compose_cmd([])


def test_slugifies_uppercase_and_punctuation():
    runner = _make_runner_at(Path("/tmp/MY Project Dir!"))
    name = runner.compose_project_name
    # No spaces, no '!', lowercase only.
    assert " " not in name
    assert "!" not in name
    assert name == name.lower()
    assert name.startswith("bedlam-")
