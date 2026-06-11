"""Tests for ``template_icon_label_check``.

The check ships with an empty-violation invariant against the live
codebase (pinned by ``test_live_codebase_is_clean`` below). The rest
pins the rules in isolation: each shape of "raw icon adjacent to text"
fires, allowlisted files are skipped, and the legitimately-allowed
adjacent shapes (next tag, next Jinja block, parent close) do not.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.dev.template_icon_label_check import (
    ALLOWLIST,
    find_violations,
)


@pytest.fixture
def src_root(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    root.mkdir(parents=True)
    return root


def _write(root: Path, rel_path: str, body: str) -> Path:
    file = root / rel_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return file


# --- Violation shapes -------------------------------------------------


def test_flush_text_after_icon_is_a_violation(src_root: Path) -> None:
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock"></i>Locked',
    )
    assert len(find_violations([file], src_root)) == 1


def test_flush_expression_after_icon_is_a_violation(src_root: Path) -> None:
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock"></i>{{ label }}',
    )
    assert len(find_violations([file], src_root)) == 1


def test_literal_space_then_text_is_a_violation(src_root: Path) -> None:
    """The ``<i></i> Label`` shape (one literal space) is the classic
    'looks fine, doubles the gap' bug — flag it."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-check"></i> Locked',
    )
    assert len(find_violations([file], src_root)) == 1


def test_newline_then_indent_then_text_is_a_violation(src_root: Path) -> None:
    """The exact shape djlint creates when it reformats a long start
    tag — a newline and an indent between ``</i>`` and the label."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        """
        <a class="locked-link"
           data-locked-cta="reason">
          <i class="icon-lock" aria-hidden="true"></i>
          Locked
        </a>
        """,
    )
    assert len(find_violations([file], src_root)) == 1


def test_icon_with_extra_classes_still_caught(src_root: Path) -> None:
    """The class attribute may carry other classes alongside the
    icon-glyph class."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock muted ghost"></i>Hi',
    )
    assert len(find_violations([file], src_root)) == 1


def test_icon_with_aria_hidden_still_caught(src_root: Path) -> None:
    """Adding ``aria-hidden="true"`` doesn't excuse the spacing bug."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock" aria-hidden="true"></i>Hi',
    )
    assert len(find_violations([file], src_root)) == 1


# --- Allowed adjacent shapes -----------------------------------------


def test_icon_then_span_wrapper_is_allowed(src_root: Path) -> None:
    """A ``<span>`` wrapper around the label carries its own class for
    CSS targeting — this shape is correct (no whitespace text-node) and
    needs no macro."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock"></i><span class="x">Hi</span>',
    )
    assert find_violations([file], src_root) == []


def test_icon_then_jinja_block_is_allowed(src_root: Path) -> None:
    """The ``{%- ... -%}`` block strips its own surrounding whitespace
    — output is flush, no bug. (See ``_feed_row.html`` for live use.)"""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        """
        <span>
        <i class="icon-map-pin"></i>
        {%- if city -%}{{ city }}{%- endif -%}
        </span>
        """,
    )
    assert find_violations([file], src_root) == []


def test_icon_then_jinja_comment_is_allowed(src_root: Path) -> None:
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<i class="icon-lock"></i>{# narration #}<span>Hi</span>',
    )
    assert find_violations([file], src_root) == []


def test_icon_then_parent_close_is_allowed(src_root: Path) -> None:
    """A pure icon — no label, just the glyph — is fine."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '<button><i class="icon-menu"></i></button>',
    )
    assert find_violations([file], src_root) == []


# --- Comments don't trigger -------------------------------------------


def test_icon_in_jinja_comment_doesnt_trigger(src_root: Path) -> None:
    """A docstring mentioning ``<i class="icon-...">Label`` (the very
    pattern this lint forbids) shouldn't itself trip the lint."""
    file = _write(
        src_root,
        "framework/templates/_shared/widget.html",
        '{# bad: <i class="icon-lock"></i>Label #}',
    )
    assert find_violations([file], src_root) == []


# --- Allowlist --------------------------------------------------------


def test_icon_label_macro_file_is_allowlisted(src_root: Path) -> None:
    """The one place in the repo where the raw pattern is legal —
    the macro that owns the contract."""
    file = _write(
        src_root,
        "framework/templates/_shared/icon_label.html",
        '<i class="icon-{{ icon }}"></i>{{ label }}',
    )
    assert find_violations([file], src_root) == []


def test_components_showcase_is_allowlisted(src_root: Path) -> None:
    file = _write(
        src_root,
        "domain/templates/dev/components.html",
        '<i class="icon-lock"></i>Showcase label',
    )
    assert find_violations([file], src_root) == []


def test_non_allowlisted_file_triggers(src_root: Path) -> None:
    file = _write(
        src_root,
        "domain/templates/clinicians/detail.html",
        '<i class="icon-lock"></i>Locked',
    )
    assert len(find_violations([file], src_root)) == 1


# --- Live-codebase invariant -----------------------------------------


def test_live_codebase_is_clean() -> None:
    """The live codebase must be free of raw icon-adjacent text — every
    site composes ``icon_label(icon, label)`` from
    ``_shared/icon_label.html``. A regression here means a template
    hand-rolled the icon+text pair instead of going through the macro."""
    project_root = Path(__file__).resolve().parents[2]
    src = project_root / "src"
    files = sorted(src.rglob("*.html"))
    violations = find_violations(files, src)
    assert not violations, "\n".join(v.message() for v in violations)


def test_allowlist_only_contains_known_carveouts() -> None:
    """Pin the allowlist literal — growing it should be a deliberate
    decision, not silent drift."""
    expected = {
        "framework/templates/_shared/icon_label.html",
        "domain/templates/dev/components.html",
    }
    assert ALLOWLIST == expected
