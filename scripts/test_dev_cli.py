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


def test_run_tests_expands_contract_alias_to_full_path():
    runner = _RecordingRunner()
    TestCommands(runner).run_tests(paths=["contract"])
    assert runner.last_cmd == ["pytest", "tests/test_contract"]


def test_run_tests_leaves_non_alias_paths_untouched():
    runner = _RecordingRunner()
    TestCommands(runner).run_tests(paths=["tests/foo", "contract", "tests/bar.py"])
    assert runner.last_cmd == [
        "pytest",
        "tests/foo",
        "tests/test_contract",
        "tests/bar.py",
    ]
