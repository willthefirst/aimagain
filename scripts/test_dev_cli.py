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
