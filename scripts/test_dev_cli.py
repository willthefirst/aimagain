"""Tests for scripts/dev_cli.py."""

from __future__ import annotations

from pathlib import Path

from scripts.dev_cli import CLIRunner


def test_clirunner_resolves_project_root_from_cwd(tmp_path: Path, monkeypatch):
    subroot = tmp_path / "subroot"
    nested = subroot / "deep" / "nested"
    nested.mkdir(parents=True)
    (subroot / "pyproject.toml").write_text("[project]\nname = 'fake'\n")

    monkeypatch.chdir(nested)

    runner = CLIRunner()
    assert runner.project_root == subroot.resolve()
