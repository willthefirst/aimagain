"""Tests for `dev merge` in scripts/dev_cli.py.

The merge loop is mostly about state-machine behaviour: given a sequence
of PR statuses, what does it do next? The shell-out boundary (gh, time)
is stubbed at the method level so we can drive the loop deterministically
without sleeping.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import MergeCommands


class _RecordingRunner:
    def __init__(self) -> None:
        self.commands: List[List[str]] = []
        self.project_root = Path("/tmp")

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        self.commands.append(cmd)
        return 0


def _merge_cmd(statuses: list) -> MergeCommands:
    runner = _RecordingRunner()
    cmd = MergeCommands(runner)
    cmd.POLL_SECONDS = 0  # don't sleep in tests
    iterator = iter(statuses)
    cmd._pr_status = lambda pr: next(iterator)
    cmd._resolve_pr_number = lambda explicit: explicit if explicit else 999
    return cmd


def _green(state: str) -> dict:
    return {
        "state": "OPEN",
        "mergeStateStatus": state,
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
    }


def test_merges_when_clean_and_checks_green():
    cmd = _merge_cmd([_green("CLEAN")])
    rc = cmd.merge(pr=123)
    assert rc == 0
    assert ["gh", "pr", "merge", "--rebase", "123"] in cmd.runner.commands


def test_rebases_then_merges_when_behind_then_clean():
    cmd = _merge_cmd([_green("BEHIND"), _green("CLEAN")])
    rc = cmd.merge(pr=123)
    assert rc == 0
    # Should have called update-branch once, then merged.
    assert ["gh", "pr", "update-branch", "--rebase", "123"] in cmd.runner.commands
    assert ["gh", "pr", "merge", "--rebase", "123"] in cmd.runner.commands
    # And the rebase came first.
    rebase_idx = cmd.runner.commands.index(
        ["gh", "pr", "update-branch", "--rebase", "123"]
    )
    merge_idx = cmd.runner.commands.index(["gh", "pr", "merge", "--rebase", "123"])
    assert rebase_idx < merge_idx


def test_aborts_on_failing_checks():
    failing = {
        "state": "OPEN",
        "mergeStateStatus": "BLOCKED",
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}
        ],
    }
    cmd = _merge_cmd([failing])
    rc = cmd.merge(pr=123)
    assert rc == 3
    # Did NOT attempt merge or update-branch.
    assert all("merge" not in c[2] for c in cmd.runner.commands if len(c) >= 3)
    assert not any("update-branch" in c for c in cmd.runner.commands)


def test_recognises_already_merged_pr():
    cmd = _merge_cmd([{"state": "MERGED", "mergeStateStatus": "CLEAN"}])
    rc = cmd.merge(pr=123)
    assert rc == 0
    # No further action — PR is already merged.
    assert cmd.runner.commands == []


def test_method_flag_is_forwarded_to_gh_pr_merge():
    cmd = _merge_cmd([_green("CLEAN")])
    cmd.merge(pr=123, method="merge")
    assert ["gh", "pr", "merge", "--merge", "123"] in cmd.runner.commands


def test_fails_fast_when_no_pr_number_resolvable(capsys):
    runner = _RecordingRunner()
    cmd = MergeCommands(runner)
    cmd._resolve_pr_number = lambda explicit: None
    rc = cmd.merge(pr=None)
    assert rc == 1
    out = capsys.readouterr().out
    assert "Could not determine PR number" in out
