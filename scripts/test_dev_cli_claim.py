"""Tests for `dev claim` in scripts/dev_cli.py.

The claim flow has three observable outcomes: won, lost, errored. Tests
stub the `_gh_json` boundary (which wraps subprocess+gh+json) and the
`runner.run_command` boundary (which performs the actual mutation), so
the state machine is exercised without external network.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from scripts.dev_cli import ClaimCommands


class _RecordingRunner:
    def __init__(self) -> None:
        self.commands: List[List[str]] = []
        self.project_root = Path("/tmp")

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> int:
        self.commands.append(cmd)
        return 0


def _claim_cmd(json_responses: dict) -> ClaimCommands:
    """`json_responses` maps a key (`view-before`, `view-after`, `user`)
    to the dict returned by the corresponding `_gh_json` call.
    """
    runner = _RecordingRunner()
    cmd = ClaimCommands(runner)
    state = {"view_calls": 0}

    def _stub(args):
        if args[0] == "api" and args[1] == "user":
            return json_responses.get("user")
        if args[0] == "issue" and args[1] == "view":
            state["view_calls"] += 1
            key = "view-after" if state["view_calls"] >= 2 else "view-before"
            return json_responses.get(key)
        return None

    cmd._gh_json = _stub
    return cmd


def test_claim_succeeds_for_unassigned_open_issue():
    cmd = _claim_cmd(
        {
            "user": {"login": "alice"},
            "view-before": {
                "assignees": [],
                "state": "OPEN",
                "title": "fix something",
            },
            "view-after": {"assignees": [{"login": "alice"}]},
        }
    )
    rc = cmd.claim(123)
    assert rc == 0
    assert [
        "gh",
        "issue",
        "edit",
        "123",
        "--add-assignee",
        "alice",
    ] in cmd.runner.commands


def test_claim_returns_1_when_already_claimed():
    cmd = _claim_cmd(
        {
            "user": {"login": "alice"},
            "view-before": {
                "assignees": [{"login": "bob"}],
                "state": "OPEN",
                "title": "fix",
            },
        }
    )
    rc = cmd.claim(123)
    assert rc == 1
    # No edit was attempted.
    assert not any("edit" in c for c in cmd.runner.commands)


def test_claim_returns_2_when_issue_is_closed():
    cmd = _claim_cmd(
        {
            "user": {"login": "alice"},
            "view-before": {
                "assignees": [],
                "state": "CLOSED",
                "title": "fix",
            },
        }
    )
    rc = cmd.claim(123)
    assert rc == 2


def test_claim_loses_race_via_tiebreak_and_unassigns():
    # Between view-before and view-after, two agents both assigned themselves.
    # Lexical tiebreak: 'aaron' wins over 'alice'; 'alice' should back off.
    cmd = _claim_cmd(
        {
            "user": {"login": "alice"},
            "view-before": {"assignees": [], "state": "OPEN", "title": "x"},
            "view-after": {"assignees": [{"login": "alice"}, {"login": "aaron"}]},
        }
    )
    rc = cmd.claim(123)
    assert rc == 1
    # Should have unassigned alice.
    assert [
        "gh",
        "issue",
        "edit",
        "123",
        "--remove-assignee",
        "alice",
    ] in cmd.runner.commands


def test_claim_with_explicit_assignee_skips_user_lookup():
    cmd = _claim_cmd(
        {
            "user": None,  # would fail current-user lookup
            "view-before": {"assignees": [], "state": "OPEN", "title": "x"},
            "view-after": {"assignees": [{"login": "bot"}]},
        }
    )
    rc = cmd.claim(123, assignee="bot")
    assert rc == 0


def test_list_unclaimed_invokes_no_assignee_search():
    runner = _RecordingRunner()
    cmd = ClaimCommands(runner)
    cmd.list_unclaimed(limit=50)
    assert any(
        c[:2] == ["gh", "issue"] and "no:assignee state:open" in c
        for c in runner.commands
    )


def test_list_claimed_uses_current_user_when_no_assignee_passed():
    runner = _RecordingRunner()
    cmd = ClaimCommands(runner)
    cmd._gh_json = lambda args: {"login": "alice"}
    cmd.list_claimed()
    assert any("assignee:alice state:open" in c for c in runner.commands)
