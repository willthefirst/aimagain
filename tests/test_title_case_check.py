"""Tests for `scripts/dev/title_case_check.py`.

The checker enforces sentence case on Markdown headers, HTML/Jinja headings,
and similar prose. Code embedded in Markdown fenced code blocks is NOT prose
and must be skipped — otherwise Python `# comments` inside a fence get
mistaken for level-1 headings, which causes spurious lint failures and was
the source of recurring friction during agent-driven doc edits.

For HTML/Jinja the checker parses the document with selectolax and lints
only text nodes inside an allowlist of content elements (plus a few
user-facing attribute values). The previous regex-over-raw-text approach
couldn't tell text nodes from attribute values, which produced false
positives on inline ``style="..."`` and required a hand-curated CSS
property allowlist; those tests live below.
"""

import textwrap
from pathlib import Path

from scripts.dev.title_case_check import TitleCaseChecker


def _write_md(tmp_path: Path, body: str) -> Path:
    file = tmp_path / "doc.md"
    file.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return file


def _write_html(tmp_path: Path, body: str, name: str = "page.html") -> Path:
    file = tmp_path / name
    file.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return file


def _check(file: Path) -> list:
    checker = TitleCaseChecker(fix_mode=False, respect_gitignore=False)
    return checker.check_file(file)


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


# ---------------------------------------------------------------------------
# Parsed-mode HTML/Jinja checker
#
# These cases used to be handled — partially and unreliably — by line-based
# regex plus an ad-hoc CSS-property allowlist. The checker now parses the
# document and lints only structurally identified prose, which is what these
# tests pin down. They are also the regression baseline for the rewrite: if
# any of these starts firing again, a parser bug has crept in.
# ---------------------------------------------------------------------------


def test_inline_style_no_false_positive(tmp_path):
    """Inline ``style="..."`` is an attribute value, not prose. The previous
    regex approach matched ``gap:`` from CSS as a "label needing
    title-case", which is exactly the bug this rewrite eliminates."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <ul style="display: flex; gap: 1rem; margin: 0">
          <li>Items</li>
        </ul>
        </body></html>
        """,
    )
    violations = _check(file)
    assert not any(
        v["original"].lower().startswith(("gap", "display", "margin"))
        for v in violations
    ), f"CSS-in-style should not be linted, got: {violations}"


def test_attribute_names_and_unrelated_values_ignored(tmp_path):
    """``href``, ``class``, ``id``, ``data-*`` and tag names themselves are
    never prose. Only the small allowlist of user-facing attributes
    (``alt``, ``title``, ``placeholder``, ``aria-label``,
    ``aria-description``) is linted."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <a href="/Posts" class="Foo Bar" id="MyId" data-thing="X Y">link</a>
        </body></html>
        """,
    )
    violations = _check(file)
    bad = [
        v for v in violations if v["original"] in {"/Posts", "Foo Bar", "MyId", "X Y"}
    ]
    assert not bad, f"Non-allowlisted attribute values must not lint, got: {bad}"


def test_lintable_attribute_value_is_checked(tmp_path):
    file = _write_html(tmp_path, "<html><body><img alt='Profile Photo'></body></html>")
    violations = _check(file)
    assert any(
        v["original"] == "Profile Photo" for v in violations
    ), f"alt attribute value should lint, got: {violations}"


def test_text_node_inside_link_is_linted(tmp_path):
    file = _write_html(
        tmp_path,
        "<html><body><a href='/x'>Posts Page</a></body></html>",
    )
    violations = _check(file)
    assert any(v["original"] == "Posts Page" for v in violations)


def test_jinja_in_attribute_does_not_break_parsing(tmp_path):
    """A Jinja expression inside an attribute value (``href="{{ url }}"``)
    must not derail the parser or cause the surrounding prose to be
    mis-linted. The expression is replaced with a sentinel before parsing
    and the link text is what we actually want to check."""
    file = _write_html(
        tmp_path,
        """
        {% extends "base.html" %}
        {% block content %}
        <a href="{{ url_for('foo') }}">View Post Now</a>
        {% endblock %}
        """,
        name="page.jinja",
    )
    violations = _check(file)
    originals = {v["original"] for v in violations}
    assert "View Post Now" in originals, f"Got: {violations}"
    # The sentinel must never leak into a violation.
    assert not any("JINJAPLACEHOLDER" in v["original"] for v in violations)


def test_jinja_substitution_in_text_is_skipped(tmp_path):
    """When prose contains a Jinja expression ``{{ x }}``, we cannot judge
    the rendered case — the whole text is skipped rather than flagged
    against the placeholder."""
    file = _write_html(
        tmp_path,
        "<html><body><p>Welcome, {{ user.name }}!</p></body></html>",
    )
    violations = _check(file)
    assert violations == [], f"Jinja-bearing text should be skipped, got: {violations}"


def test_script_and_style_subtrees_skipped(tmp_path):
    """``<script>`` and ``<style>`` content is code, not prose. The walker
    must never descend into either."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <style>.x { Color: Red; }</style>
        <script>const FooBar = 1;</script>
        <p>Real prose here.</p>
        </body></html>
        """,
    )
    violations = _check(file)
    assert not any(
        "Color" in v["original"] or "FooBar" in v["original"] for v in violations
    ), f"Code content must not be linted, got: {violations}"


def test_h1_through_h6_all_linted(tmp_path):
    """Regression guard: the regex linter checked h1-h6; the parser must
    keep that coverage."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <h1>Bad Heading One</h1>
        <h6>Bad Heading Six</h6>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Bad Heading One" in originals
    assert "Bad Heading Six" in originals


def test_list_and_table_cell_linted(tmp_path):
    """The expanded element set covers list items and table cells, since
    those frequently hold short label-like prose in templates."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <ul><li>Item One</li></ul>
        <table><tr><th>Header One</th><td>Cell One</td></tr></table>
        </body></html>
        """,
    )
    originals = {v["original"] for v in _check(file)}
    assert "Item One" in originals
    assert "Header One" in originals
    assert "Cell One" in originals


def test_multi_sentence_paragraph_each_clause_validated(tmp_path):
    """A ``<p>`` containing multiple sentences is checked sentence-by-
    sentence so that "Forgot your password? Reset here" passes (each clause
    starts with a capital and is otherwise sentence case)."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <p>Forgot your password? Reset here</p>
        <p>Hello world. This is fine.</p>
        </body></html>
        """,
    )
    violations = _check(file)
    assert violations == [], f"Multi-sentence prose should pass, got: {violations}"


def test_numbered_markdown_heading_not_split_as_sentence(tmp_path):
    """Markdown headings like ``### 1. ssh to droplet`` must not be flagged:
    the leading ``1.`` is a numbering prefix, not a sentence end. This
    regression guards the multi-sentence detector from splitting on
    digit-period."""
    file = _write_md(
        tmp_path,
        """
        ### 1. ssh to droplet

        body
        """,
    )
    assert _check(file) == []


def test_unparseable_input_warns_and_returns_empty(tmp_path, capsys):
    """If selectolax cannot parse the document we skip it with a warning,
    not fall back to raw-text regex (the bug we just fixed)."""
    # selectolax is permissive; force the parser code path with a binary
    # blob in a .html file is hard. Instead, force the fail path by
    # patching the parser to raise.
    from scripts.dev import title_case_check as mod

    file = _write_html(tmp_path, "<p>Hello</p>")
    real = mod.HTMLParser

    class _BoomParser:
        def __init__(self, *_a, **_k):
            raise RuntimeError("simulated parse failure")

    mod.HTMLParser = _BoomParser
    try:
        violations = _check(file)
    finally:
        mod.HTMLParser = real
    captured = capsys.readouterr()
    assert violations == []
    assert "could not parse" in captured.err


def test_inline_title_case_ignore_marker_suppresses(tmp_path):
    """``{# title-case-ignore #}`` on the same line as a violation
    suppresses it. The escape hatch must keep working in parsed mode."""
    file = _write_html(
        tmp_path,
        """
        <html><body>
        <dt>ZIP</dt>{# title-case-ignore #}
        </body></html>
        """,
    )
    assert _check(file) == []


def test_titleignore_file_skips_whole_file(tmp_path):
    """A ``.titleignore`` listing a file pattern excludes that file even
    when it has clear violations."""
    file = _write_html(tmp_path, "<html><body><h1>Bad Heading</h1></body></html>")
    (tmp_path / ".titleignore").write_text("page.html\n", encoding="utf-8")
    assert _check(file) == []


def test_fix_mode_replaces_text_in_html(tmp_path):
    file = _write_html(tmp_path, "<html><body><h1>Bad Heading</h1></body></html>")
    checker = TitleCaseChecker(fix_mode=True, respect_gitignore=False)
    violations = checker.check_file(file)
    assert violations
    checker.fix_file(file, violations)
    assert "Bad heading" in file.read_text(encoding="utf-8")
    # Running again on the fixed file produces no violations.
    assert TitleCaseChecker(respect_gitignore=False).check_file(file) == []
