"""Tests for `dev push` in scripts/dev_cli.py.

The command shells out to `git`, `gh`, and `input()`. Tests stub the
external interactions directly on the PushCommands instance — the
contract under test is "given these overlap signals, do we prompt and
do we honour the answer?", not the shell incantations themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import PushCommands


class _RecordingRunner:
    def __init__(self) -> None:
        self.last_cmd: Optional[List[str]] = None
        self.project_root = Path("/tmp")

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        self.last_cmd = cmd
        return 0


def _push_cmd(branch: str, prs: list, commits: list) -> PushCommands:
    runner = _RecordingRunner()
    cmd = PushCommands(runner)
    cmd._current_branch = lambda: branch
    cmd._gh_existing_prs = lambda issue: prs
    cmd._grep_main_log = lambda issue: commits
    return cmd


# --- branch-name parsing ------------------------------------------------


def test_extracts_issue_number_from_fix_branch():
    cmd = _push_cmd("fix/697-foo", [], [])
    assert cmd._issue_number_from_branch("fix/697-foo") == 697


def test_extracts_issue_number_from_issue_branch():
    cmd = _push_cmd("issue-697-foo", [], [])
    assert cmd._issue_number_from_branch("issue-697-foo") == 697


def test_extracts_issue_number_from_claude_branch():
    cmd = _push_cmd("claude/fix-697-foo", [], [])
    assert cmd._issue_number_from_branch("claude/fix-697-foo") == 697


def test_returns_none_when_no_issue_number_in_branch():
    cmd = _push_cmd("misc-refactor", [], [])
    assert cmd._issue_number_from_branch("misc-refactor") is None


# --- prompt + push behavior --------------------------------------------


def test_pushes_without_prompt_when_no_overlaps(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    cmd = _push_cmd("fix/697-foo", prs=[], commits=[])
    rc = cmd.push()
    assert rc == 0
    assert cmd.runner.last_cmd == ["git", "push", "-u", "origin", "fix/697-foo"]


def test_prompts_and_aborts_when_pr_already_exists(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    cmd = _push_cmd(
        "fix/697-foo",
        prs=[{"number": 723, "state": "merged", "title": "fix: foo"}],
        commits=[],
    )
    rc = cmd.push()
    assert rc == 2
    assert cmd.runner.last_cmd is None  # never reached git push
    out = capsys.readouterr().out
    assert "Issue #697 may already be addressed" in out
    assert "PR #723" in out


def test_prompts_and_pushes_when_user_confirms(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    cmd = _push_cmd(
        "fix/697-foo",
        prs=[{"number": 723, "state": "open", "title": "fix: foo"}],
        commits=[],
    )
    rc = cmd.push()
    assert rc == 0
    assert cmd.runner.last_cmd == ["git", "push", "-u", "origin", "fix/697-foo"]


def test_yes_flag_bypasses_prompt_entirely(monkeypatch, capsys):
    # If the prompt code runs at all, input() will raise — proves we skip it.
    def _boom(_prompt=""):
        raise AssertionError("prompt should not be called")

    monkeypatch.setattr("builtins.input", _boom)
    cmd = _push_cmd(
        "fix/697-foo",
        prs=[{"number": 723, "state": "merged", "title": "fix: foo"}],
        commits=["abc123 fix: foo (#697)"],
    )
    rc = cmd.push(yes=True)
    assert rc == 0
    assert cmd.runner.last_cmd == ["git", "push", "-u", "origin", "fix/697-foo"]


def test_main_log_overlap_also_triggers_prompt(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    cmd = _push_cmd(
        "fix/697-foo",
        prs=[],
        commits=["abc123 fix: foo (#697)"],
    )
    rc = cmd.push()
    assert rc == 2
    out = capsys.readouterr().out
    assert "abc123 fix: foo (#697)" in out


def test_force_flag_adds_force_with_lease(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    cmd = _push_cmd("fix/697-foo", prs=[], commits=[])
    cmd.push(force=True)
    assert cmd.runner.last_cmd[-1] == "--force-with-lease"


def test_branch_without_issue_number_pushes_unconditionally(monkeypatch):
    # No issue number in branch → no API calls, no prompt.
    def _boom(_prompt=""):
        raise AssertionError("prompt should not be called")

    monkeypatch.setattr("builtins.input", _boom)
    cmd = _push_cmd("misc-refactor", prs=[], commits=[])
    rc = cmd.push()
    assert rc == 0
    assert cmd.runner.last_cmd == ["git", "push", "-u", "origin", "misc-refactor"]
