"""Tests for scripts/dev_cli.py."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import CLIRunner, TestCommands


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
