"""Tests for ``template_component_check``.

The check ships with an empty-violation invariant against the live
codebase (pinned by ``test_live_codebase_is_clean`` below). The rest
of the suite pins the rules in isolation: each forbidden tag fires,
allowlisted files are skipped, the hidden-input carve-out is honored,
and tags mentioned inside comments don't trigger.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.dev.template_component_check import (
    ALLOWLIST,
    FORBIDDEN,
    find_violations,
)


@pytest.fixture
def templates_root(tmp_path: Path) -> Path:
    root = tmp_path / "src" / "domain" / "templates"
    root.mkdir(parents=True)
    return root


def _write(root: Path, rel_path: str, body: str) -> Path:
    file = root / rel_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return file


# --- Forbidden-tag detection ------------------------------------------


def test_raw_button_is_a_violation(templates_root: Path) -> None:
    file = _write(
        templates_root,
        "clinicians/detail.html",
        '<button type="button">Click</button>',
    )
    violations = find_violations([file], templates_root)
    assert len(violations) == 1
    assert violations[0].tag == "button"


def test_raw_form_is_a_violation(templates_root: Path) -> None:
    file = _write(
        templates_root,
        "organizations/form_edit.html",
        '<form hx-patch="/x">save</form>',
    )
    violations = find_violations([file], templates_root)
    assert any(v.tag == "form" for v in violations)


def test_raw_dl_is_a_violation(templates_root: Path) -> None:
    file = _write(
        templates_root,
        "programs/detail.html",
        "<dl><dt>k</dt><dd>v</dd></dl>",
    )
    violations = find_violations([file], templates_root)
    tags = {v.tag for v in violations}
    assert {"dl", "dt", "dd"}.issubset(tags)


def test_every_forbidden_tag_has_a_macro_suggestion() -> None:
    """The error message names the macro to use instead. Without the
    suggestion the lint reads as a NACK with no guidance — every entry
    in ``FORBIDDEN`` must be load-bearing prose."""
    for tag, suggestion in FORBIDDEN.items():
        assert (
            len(suggestion) > 20
        ), f"`{tag}` suggestion is too terse to guide a fix: {suggestion!r}"


# --- Allowlist ---------------------------------------------------------


def test_allowlisted_file_is_skipped(templates_root: Path) -> None:
    """A file in ``ALLOWLIST`` may emit any of the forbidden tags
    without triggering. (Use sparingly — the allowlist is the
    explicit-exception register, not the default escape valve.)"""
    file = _write(
        templates_root,
        "dev/components.html",
        "<button>showcase</button><form><input><select><dl><article><menu>",
    )
    assert find_violations([file], templates_root) == []


def test_allowlisted_directory_skips_nested_files(templates_root: Path) -> None:
    """``auth/`` is allowlisted with a trailing slash — every file
    under it (including nested subdirs) skips the check."""
    file = _write(
        templates_root,
        "auth/login.html",
        '<form><input type="email"><button>Log in</button></form>',
    )
    assert find_violations([file], templates_root) == []


def test_non_allowlisted_files_trigger(templates_root: Path) -> None:
    """Sanity check: a fresh file path that isn't in the allowlist
    DOES trigger when it emits a forbidden tag."""
    file = _write(
        templates_root,
        "new_cluster/list.html",
        "<article>hi</article>",
    )
    assert len(find_violations([file], templates_root)) == 1


# --- Hidden-input carve-out -------------------------------------------


def test_hidden_input_does_not_violate(templates_root: Path) -> None:
    """`<input type="hidden">` is structural form plumbing (kind
    discriminators, CSRF, etc.), not a user-visible control. The
    check skips it explicitly."""
    file = _write(
        templates_root,
        "posts/_form_referral.html",
        '<input type="hidden" name="kind" value="referral" />',
    )
    assert find_violations([file], templates_root) == []


def test_visible_input_does_violate(templates_root: Path) -> None:
    """A non-hidden input still violates — those go through the
    `text_field` / `select_field` / etc. macros."""
    file = _write(
        templates_root,
        "posts/some_form.html",
        '<input type="text" name="title" />',
    )
    assert len(find_violations([file], templates_root)) == 1


# --- Comment stripping ------------------------------------------------


def test_jinja_comment_mention_does_not_trigger(templates_root: Path) -> None:
    """A `{# docstring mentioning <article> #}` is documentation, not
    an emission. Multi-line Jinja comments are stripped before scan."""
    file = _write(
        templates_root,
        "organizations/list.html",
        """
        {# This template wraps items in `<article>` via the `card`
           macro — the raw element never appears here. #}
        """,
    )
    assert find_violations([file], templates_root) == []


def test_html_comment_mention_does_not_trigger(templates_root: Path) -> None:
    """Same rule for HTML comments — `<!-- <form> goes here -->` is
    docs, not an emission."""
    file = _write(
        templates_root,
        "programs/detail.html",
        "<!-- a <form> would live here but doesn't -->",
    )
    assert find_violations([file], templates_root) == []


def test_violation_line_number_is_preserved_after_comment_stripping(
    templates_root: Path,
) -> None:
    """Comments are stripped by space-replacement (not deletion) so the
    line numbers in the violation report still match the original file.
    A multi-line Jinja docstring above a real violation shouldn't
    knock the reported line number out of sync."""
    file = _write(
        templates_root,
        "users/widget.html",
        """\
        {# multi-line
           docstring
           mentioning <button> #}
        <button>real</button>
        """,
    )
    violations = find_violations([file], templates_root)
    assert len(violations) == 1
    assert violations[0].line == 4


# --- Live-codebase invariant ------------------------------------------


def test_live_codebase_is_clean() -> None:
    """The live codebase under ``src/domain/templates/`` must be free of
    raw HTML primitives (modulo the documented allowlist). This is the
    real protection — every other test pins the lint's behavior; this
    one pins the goal state.

    A regression here means a domain template hand-rolled an element
    that should have been a macro. Either migrate to the macro or
    (if it's a genuine one-off) add the file to ``ALLOWLIST`` with a
    one-line justification."""
    project_root = Path(__file__).resolve().parents[2]
    root = project_root / "src" / "domain" / "templates"
    files = sorted(root.rglob("*.html"))
    violations = find_violations(files, root)
    assert not violations, "\n".join(v.message() for v in violations)


def test_allowlist_only_contains_known_carveouts() -> None:
    """Pin the allowlist entries against the documented set — adding to
    it should be a deliberate decision, not silent drift. A new entry
    here means the corresponding ``ALLOWLIST`` literal in the script
    also gets updated."""
    expected = {
        "dev/components.html",
        "auth/",
        "users/detail.html",
        "users/email_form.html",
        "posts/_shared/_message_form.html",
        "posts/_shared/_connect_panel.html",
        "users/access/capabilities/index.html",
    }
    assert ALLOWLIST == expected
