"""Tests for `dev merge` in scripts/dev_cli.py.

With the merge queue enabled, `dev merge` enables auto-merge via
`gh pr merge --auto` and then polls until the queue lands the PR or a
check fails. The shell-out boundary (gh, time) is stubbed so we can
drive the loop deterministically without sleeping.
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


def _green(state: str) -> dict:
    return {
        "state": "OPEN",
        "mergeStateStatus": state,
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
        ],
    }


def _merged() -> dict:
    return {"state": "MERGED", "mergeStateStatus": "CLEAN"}


def test_enables_auto_merge_and_waits_for_queue_to_land():
    # initial check (clean) → enable auto-merge → poll once and see MERGED.
    cmd = _merge_cmd([_green("CLEAN"), _merged()])
    rc = cmd.merge(pr=123)
    assert rc == 0
    assert ["gh", "pr", "merge", "123", "--auto", "--squash"] in cmd.runner.commands


def test_default_method_is_squash():
    cmd = _merge_cmd([_green("CLEAN"), _merged()])
    cmd.merge(pr=123)
    # Squash is the queue-configured method; default must match.
    assert ["gh", "pr", "merge", "123", "--auto", "--squash"] in cmd.runner.commands


def test_method_flag_is_forwarded():
    cmd = _merge_cmd([_green("CLEAN"), _merged()])
    cmd.merge(pr=123, method="rebase")
    assert ["gh", "pr", "merge", "123", "--auto", "--rebase"] in cmd.runner.commands


def test_aborts_on_failing_checks_before_enabling_auto_merge():
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
    # Did NOT attempt to enable auto-merge — would have burned a queue slot.
    assert cmd.runner.commands == []


def test_detects_failure_while_waiting_in_queue():
    failing = {
        "state": "OPEN",
        "mergeStateStatus": "BLOCKED",
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}
        ],
    }
    # initial clean, auto-merge submitted, then a queued CI run fails.
    cmd = _merge_cmd([_green("CLEAN"), failing])
    rc = cmd.merge(pr=123)
    assert rc == 3
    # Auto-merge was attempted before the failure showed up.
    assert ["gh", "pr", "merge", "123", "--auto", "--squash"] in cmd.runner.commands


def test_recognises_already_merged_pr():
    cmd = _merge_cmd([_merged()])
    rc = cmd.merge(pr=123)
    assert rc == 0
    # No auto-merge call — PR is already merged.
    assert cmd.runner.commands == []


def test_fails_fast_when_no_pr_number_resolvable(capsys):
    runner = _RecordingRunner()
    cmd = MergeCommands(runner)
    cmd._resolve_pr_number = lambda explicit: None
    rc = cmd.merge(pr=None)
    assert rc == 1
    out = capsys.readouterr().out
    assert "Could not determine PR number" in out
