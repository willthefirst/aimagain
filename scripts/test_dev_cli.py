"""Tests for scripts/dev_cli.py."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import CLIRunner, SeedCommands, TestCommands, WorktreeCommands


def test_clirunner_resolves_project_root_from_cwd(tmp_path: Path, monkeypatch):
    subroot = tmp_path / "subroot"
    nested = subroot / "deep" / "nested"
    nested.mkdir(parents=True)
    (subroot / "pyproject.toml").write_text("[project]\nname = 'fake'\n")

    monkeypatch.chdir(nested)

    runner = CLIRunner()
    assert runner.project_root == subroot.resolve()


class _RecordingRunner:
    """Stand-in for CLIRunner that captures the pytest command instead of running it."""

    def __init__(self) -> None:
        self.last_cmd: Optional[List[str]] = None
        # `_dirty_files` in TestCommands shells out to `git status` against
        # this directory. Tests that don't care about fmt-mutation surfacing
        # rely on the lookup returning an empty set silently — pointing at
        # /tmp does that without contaminating the repo.
        self.project_root = Path("/tmp")

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        self.last_cmd = cmd
        return 0


class _FakeQuality:
    """Records fmt/lint invocations so tests can assert call order without
    spawning real subprocesses. The recorded labels feed the
    `_dispatch_order` fixture below."""

    def __init__(self, fmt_rc: int = 0, lint_rc: int = 0) -> None:
        self.fmt_rc = fmt_rc
        self.lint_rc = lint_rc
        self.calls: List[str] = []

    def fmt(self) -> int:
        self.calls.append("fmt")
        return self.fmt_rc

    def lint(self) -> int:
        self.calls.append("lint")
        return self.lint_rc


def _quality_aware_runner() -> tuple[_RecordingRunner, _FakeQuality]:
    """Construct the runner/quality pair the rest of the file uses.

    Centralized so the test-level invariant — `last_cmd` is `None` until
    pytest is invoked — stays obvious in each callsite."""
    return _RecordingRunner(), _FakeQuality()


def test_run_tests_expands_contract_alias_to_full_path():
    runner, quality = _quality_aware_runner()
    TestCommands(runner, quality).run_tests(paths=["contract"], skip_lint=True)
    assert runner.last_cmd == ["pytest", "tests/test_contract"]


def test_run_tests_leaves_non_alias_paths_untouched():
    runner, quality = _quality_aware_runner()
    TestCommands(runner, quality).run_tests(
        paths=["tests/foo", "contract", "tests/bar.py"], skip_lint=True
    )
    assert runner.last_cmd == [
        "pytest",
        "tests/foo",
        "tests/test_contract",
        "tests/bar.py",
    ]


# --- #648: fmt → lint → pytest pre-step ----------------------------------


def test_run_tests_default_dispatches_fmt_then_lint_then_pytest():
    """`dev test` (no flag) runs fmt + lint as a pre-step before
    invoking pytest. Order is locked in: fmt first (auto-fix the easy
    cases) then lint (catch what fmt can't), then pytest.

    Regression for #648 — agents kept landing tests-pass-but-lint-fails
    PRs because the inner loop didn't surface formatting violations
    until after the test suite finished."""
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests()
    assert quality.calls == ["fmt", "lint"]
    assert runner.last_cmd == ["pytest"]
    assert rc == 0


def test_run_tests_skip_lint_dispatches_only_pytest():
    """`--skip-lint` bypasses fmt + lint entirely. Used by the inner
    loop case where the developer is iterating on a failing test and
    doesn't want lint noise."""
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests(skip_lint=True)
    assert quality.calls == []
    assert runner.last_cmd == ["pytest"]
    assert rc == 0


def test_run_tests_stops_when_lint_fails_and_does_not_invoke_pytest():
    """If lint returns non-zero, pytest is never invoked — the agent
    sees the lint failure immediately instead of waiting for the test
    suite to finish first. Returns lint's exit code so CI / wrappers
    propagate the right signal."""
    runner = _RecordingRunner()
    quality = _FakeQuality(lint_rc=2)
    rc = TestCommands(runner, quality).run_tests()
    # fmt ran (auto-fix is cheap), lint ran (it's the gate), pytest did not.
    assert quality.calls == ["fmt", "lint"]
    assert runner.last_cmd is None
    assert rc == 2


def test_run_tests_stops_when_fmt_fails_and_does_not_invoke_lint_or_pytest():
    """If `dev fmt` itself fails (e.g. Black syntax-errors on a broken
    file), short-circuit before lint or pytest. The agent fixes the
    syntax error first, then re-runs."""
    runner = _RecordingRunner()
    quality = _FakeQuality(fmt_rc=1)
    rc = TestCommands(runner, quality).run_tests()
    assert quality.calls == ["fmt"]
    assert runner.last_cmd is None
    assert rc == 1


# --- #745: surface fmt-step mutations -----------------------------------


def test_run_tests_warns_when_fmt_modifies_a_previously_clean_file(capsys):
    """When `dev fmt` rewrites a file that was clean before, surface the
    path explicitly. Agents had been hitting "Edit failed: file modified
    since read" with no visible cause; the cause is fmt, and naming it
    saves the diagnose-from-scratch round trip. See #745."""
    runner, quality = _quality_aware_runner()
    cmd = TestCommands(runner, quality)
    # Simulate fmt rewriting one file mid-step.
    dirty_states = iter([set(), {"src/templates/login.html"}])
    cmd._dirty_files = lambda: next(dirty_states)
    rc = cmd.run_tests()
    out = capsys.readouterr().out
    assert "src/templates/login.html" in out
    assert "rewrote 1 file" in out
    assert "re-read" in out
    assert rc == 0


def test_run_tests_does_not_warn_when_fmt_changes_nothing(capsys):
    """If fmt is a no-op, no warning — silence is fine, the case we care
    about is the surprise mutation."""
    runner, quality = _quality_aware_runner()
    cmd = TestCommands(runner, quality)
    cmd._dirty_files = lambda: set()
    cmd.run_tests()
    out = capsys.readouterr().out
    assert "rewrote" not in out


def test_run_tests_does_not_warn_for_files_dirty_before_fmt(capsys):
    """Files the agent had already edited are dirty BEFORE fmt — that's
    not a fmt mutation, just the agent's own in-flight work. Only
    newly-dirty paths get surfaced."""
    runner, quality = _quality_aware_runner()
    cmd = TestCommands(runner, quality)
    pre = {"src/foo.py"}
    dirty_states = iter([pre, pre | {"src/templates/login.html"}])
    cmd._dirty_files = lambda: next(dirty_states)
    cmd.run_tests()
    out = capsys.readouterr().out
    assert "src/templates/login.html" in out
    assert "src/foo.py" not in out
    assert "rewrote 1 file" in out


# --- --affected wiring --------------------------------------------------


def test_run_tests_affected_with_explicit_paths_is_rejected():
    """`--affected` derives the path list from the diff; combining it
    with explicit paths is almost always a usage mistake. Exit 2
    (argparse convention for usage errors) so a CI invocation that
    accidentally drifts surfaces immediately."""
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests(
        affected=True, paths=["tests/foo.py"], skip_lint=True
    )
    assert rc == 2
    assert runner.last_cmd is None


def test_run_tests_affected_forwards_selected_paths_to_pytest(monkeypatch):
    """The selector decides which test files matter; the CLI passes
    that decision through to pytest verbatim. Mock the selector so we
    test the wiring, not the colocated-test heuristic (which
    `test_affected_tests.py` already pins)."""
    import scripts.affected_tests as mod

    monkeypatch.setattr(mod, "changed_files", lambda base, root: ["x.py"])
    monkeypatch.setattr(
        mod,
        "select_affected_tests",
        lambda files, root: mod.AffectedSelection(
            paths=("src/a/test_x.py",), full_suite=False, reason="stub"
        ),
    )
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests(affected=True, skip_lint=True)
    assert rc == 0
    assert runner.last_cmd == ["pytest", "src/a/test_x.py"]


def test_run_tests_affected_full_suite_runs_pytest_with_no_paths(monkeypatch):
    """Blast-radius → `pytest` with no path args, which collects
    everything via the configured `addopts`. Critical that the CLI
    doesn't pass an empty path list as a literal argument."""
    import scripts.affected_tests as mod

    monkeypatch.setattr(mod, "changed_files", lambda base, root: ["pyproject.toml"])
    monkeypatch.setattr(
        mod,
        "select_affected_tests",
        lambda files, root: mod.AffectedSelection(
            paths=(), full_suite=True, reason="stub blast radius"
        ),
    )
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests(affected=True, skip_lint=True)
    assert rc == 0
    assert runner.last_cmd == ["pytest"]


# ---------------------------------------------------------------------------
# SeedCommands._in_container
# ---------------------------------------------------------------------------


def test_in_container_true_when_dockerenv_exists():
    import unittest.mock as mock

    with mock.patch("os.path.exists", side_effect=lambda p: p == "/.dockerenv"):
        assert SeedCommands._in_container() is True


def test_in_container_false_when_dockerenv_absent():
    import unittest.mock as mock

    with mock.patch("os.path.exists", return_value=False):
        assert SeedCommands._in_container() is False


def test_run_tests_affected_empty_selection_skips_pytest(monkeypatch):
    """README-only PR: no source touched, no tests selected. The CLI
    exits 0 *without* invoking pytest — that's the entire point of
    the selector in the CI tier (don't spin up the runner for nothing)."""
    import scripts.affected_tests as mod

    monkeypatch.setattr(mod, "changed_files", lambda base, root: ["README.md"])
    monkeypatch.setattr(
        mod,
        "select_affected_tests",
        lambda files, root: mod.AffectedSelection(
            paths=(), full_suite=False, reason="docs only"
        ),
    )
    runner, quality = _quality_aware_runner()
    rc = TestCommands(runner, quality).run_tests(affected=True, skip_lint=True)
    assert rc == 0
    assert runner.last_cmd is None


# ---------------------------------------------------------------------------
# CLIRunner._derive_ports  (issue #1007)
# ---------------------------------------------------------------------------


def test_derive_ports_defaults_when_no_port_file(tmp_path: Path, monkeypatch):
    """Main checkout (no .worktree-port) returns the standard defaults."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    monkeypatch.chdir(tmp_path)
    runner = CLIRunner()
    assert runner.app_port == 8000
    assert runner.livereload_port == 35729


def test_derive_ports_reads_port_file(tmp_path: Path, monkeypatch):
    """Worktree with .worktree-port uses the stored ports."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    (tmp_path / ".worktree-port").write_text("8002 35731\n")
    monkeypatch.chdir(tmp_path)
    runner = CLIRunner()
    assert runner.app_port == 8002
    assert runner.livereload_port == 35731


def test_derive_ports_falls_back_on_corrupt_port_file(tmp_path: Path, monkeypatch):
    """Corrupt .worktree-port silently falls back to defaults."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    (tmp_path / ".worktree-port").write_text("not-a-number\n")
    monkeypatch.chdir(tmp_path)
    runner = CLIRunner()
    assert runner.app_port == 8000
    assert runner.livereload_port == 35729


def test_compose_env_injects_ports(tmp_path: Path, monkeypatch):
    """`_compose_env` injects APP_PORT and LIVERELOAD_PORT."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    (tmp_path / ".worktree-port").write_text("8003 35732\n")
    monkeypatch.chdir(tmp_path)
    runner = CLIRunner()
    env = runner._compose_env()
    assert env["APP_PORT"] == "8003"
    assert env["LIVERELOAD_PORT"] == "35732"


# ---------------------------------------------------------------------------
# WorktreeCommands._assign_worktree_port  (issue #1007)
# ---------------------------------------------------------------------------


def _make_worktree_runner(tmp_path: Path, monkeypatch) -> CLIRunner:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    monkeypatch.chdir(tmp_path)
    return CLIRunner()


def test_assign_worktree_port_starts_at_8001(tmp_path: Path, monkeypatch):
    """First worktree gets port 8001."""
    runner = _make_worktree_runner(tmp_path, monkeypatch)
    wt_cmds = WorktreeCommands(runner)
    assert wt_cmds._assign_worktree_port() == 8001


def test_assign_worktree_port_skips_used_ports(tmp_path: Path, monkeypatch):
    """Ports already taken by existing .worktree-port files are skipped."""
    runner = _make_worktree_runner(tmp_path, monkeypatch)
    wt_root = tmp_path / ".claude" / "worktrees"
    (wt_root / "issue-1").mkdir(parents=True)
    (wt_root / "issue-2").mkdir(parents=True)
    (wt_root / "issue-1" / ".worktree-port").write_text("8001 35730\n")
    (wt_root / "issue-2" / ".worktree-port").write_text("8002 35731\n")
    wt_cmds = WorktreeCommands(runner)
    assert wt_cmds._assign_worktree_port() == 8003


def test_assign_worktree_port_ignores_corrupt_sibling(tmp_path: Path, monkeypatch):
    """A corrupt sibling .worktree-port is skipped without raising."""
    runner = _make_worktree_runner(tmp_path, monkeypatch)
    wt_root = tmp_path / ".claude" / "worktrees"
    (wt_root / "issue-bad").mkdir(parents=True)
    (wt_root / "issue-bad" / ".worktree-port").write_text("oops\n")
    wt_cmds = WorktreeCommands(runner)
    assert wt_cmds._assign_worktree_port() == 8001
