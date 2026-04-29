"""Tests for `scripts/dev/title_case_check.py`.

The checker enforces sentence case on Markdown headers, HTML/Jinja headings,
and similar prose. Code embedded in Markdown fenced code blocks is NOT prose
and must be skipped — otherwise Python `# comments` inside a fence get
mistaken for level-1 headings, which causes spurious lint failures and was
the source of recurring friction during agent-driven doc edits.
"""

import textwrap
from pathlib import Path

from scripts.dev.title_case_check import TitleCaseChecker


def _write_md(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "doc.md"
    file.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return file


def test_fenced_code_block_python_comments_are_not_treated_as_headings(tmp_path):
    """A Python comment inside a ```python``` fence must NOT be flagged as
    a level-1 Markdown heading.

    This regression exists because the checker scans line-by-line for `#`
    prefixes; without fence-awareness it sees `# Some comment` inside code
    as a heading and demands sentence-case it would never naturally have.
    """
    file = _write_md(
        tmp_path,
        """
        # Real heading

        Some prose.

        ```python
        # Register me before users so that "/users/me" matches the literal
        # handler rather than being parsed as a UUID by "/users/{user_id}".
        app.include_router(me.me_router_instance)
        ```

        More prose.
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    fenced_violations = [v for v in violations if "Register" in v["original"]]
    assert fenced_violations == [], (
        f"Python comments inside fenced code should not be flagged, got: "
        f"{fenced_violations}"
    )


def test_fenced_code_block_does_not_swallow_following_headings(tmp_path):
    """The fence-tracking state must close on the second triple-backtick so
    that real Markdown headings *after* the fence are still checked."""
    file = _write_md(
        tmp_path,
        """
        # Real heading

        ```python
        # Comment that should be skipped
        ```

        ## badly cased heading after fence
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    after_fence = [v for v in violations if "badly cased" in v["original"]]
    assert len(after_fence) == 1, (
        "A miscased heading following a fenced code block should still be "
        f"caught, got violations: {violations}"
    )


def test_tilde_fenced_code_block_is_also_skipped(tmp_path):
    """Markdown supports both ``` and ~~~ as fence delimiters."""
    file = _write_md(
        tmp_path,
        """
        # Real heading

        ~~~python
        # MUST be ignored
        ~~~
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    fenced_violations = [v for v in violations if "MUST" in v["original"]]
    assert fenced_violations == [], (
        f"Comments inside ~~~ fenced blocks should be skipped, got: "
        f"{fenced_violations}"
    )


def test_real_heading_outside_any_fence_is_still_checked(tmp_path):
    """Sanity: the fix doesn't break the checker entirely."""
    file = _write_md(
        tmp_path,
        """
        # this Heading IS Wrongly cased

        Some prose.
        """,
    )

    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    violations = checker.check_file(file)

    assert any(
        "Wrongly" in v["original"] for v in violations
    ), f"A real miscased heading must still be flagged, got: {violations}"
