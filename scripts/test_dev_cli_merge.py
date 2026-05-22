"""Tests for `dev merge` in scripts/dev_cli.py.

With Mergify handling queue and merge, `dev merge` is a pure poller:
it watches the PR until merged or a check fails. No gh commands are
issued — Mergify does the work. The shell-out boundary (gh, time) is
stubbed so we can drive the loop deterministically without sleeping.
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
    cmd.POLL_SECONDS = 0
    iterator = iter(statuses)
    cmd._pr_status = lambda pr: next(iterator)
    cmd._resolve_pr_number = lambda explicit: explicit if explicit else 999
    return cmd


def _open(state: str) -> dict:
    return {
        "state": "OPEN",
        "mergeStateStatus": state,
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
    }


def _merged() -> dict:
    return {"state": "MERGED", "mergeStateStatus": "CLEAN"}


def test_exits_zero_when_mergify_lands_pr():
    cmd = _merge_cmd([_open("BLOCKED"), _merged()])
    rc = cmd.merge(pr=123)
    assert rc == 0
    # Pure watcher — no gh commands issued.
    assert cmd.runner.commands == []


def test_recognises_already_merged_pr():
    cmd = _merge_cmd([_merged()])
    rc = cmd.merge(pr=123)
    assert rc == 0
    assert cmd.runner.commands == []


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
    assert cmd.runner.commands == []


def test_reports_state_changes_while_waiting(capsys):
    cmd = _merge_cmd([_open("BLOCKED"), _open("QUEUED"), _merged()])
    cmd.merge(pr=123)
    out = capsys.readouterr().out
    assert "BLOCKED" in out
    assert "QUEUED" in out


def test_fails_fast_when_no_pr_number_resolvable(capsys):
    runner = _RecordingRunner()
    cmd = MergeCommands(runner)
    cmd._resolve_pr_number = lambda explicit: None
    rc = cmd.merge(pr=None)
    assert rc == 1
    assert "Could not determine PR number" in capsys.readouterr().out
