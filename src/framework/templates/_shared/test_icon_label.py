"""Tests for the ``icon_label(icon, label)`` macro in ``_shared/icon_label.html``.

The macro's only job is to emit `<i class="icon-{icon}" aria-hidden="true"></i>`
**flush** against its label text — no whitespace text-node between them. CSS
already supplies the icon-label gap via the
`[class^="icon-"] { margin-inline-end: 0.25em; }` rule in `base.html`; a stray
whitespace node would compound on top of it. These tests pin the flush
adjacency, the icon class formation, and the `aria-hidden` attribute so a
future refactor (or a djlint reformat) can't silently regress.
"""

from __future__ import annotations

import textwrap

from src.framework.templates._test_env import make_test_env


def _render(icon: str, label: str) -> str:
    return make_test_env().from_string(textwrap.dedent(f"""\
        {{%- from "_shared/icon_label.html" import icon_label -%}}
        {{{{ icon_label({icon!r}, {label!r}) }}}}
        """)).render()


def test_icon_label_renders_icon_and_label() -> None:
    out = _render("lock", "Locked thing")
    assert '<i class="icon-lock" aria-hidden="true"></i>' in out
    assert "Locked thing" in out


def test_icon_label_is_flush_with_no_whitespace_between_icon_and_label() -> None:
    """The bug this macro exists to prevent: a whitespace text-node between
    ``</i>`` and the label compounds with the CSS icon margin and renders as a
    visibly doubled gap. The rendered output must therefore contain the literal
    string ``</i>Label`` with no characters between."""
    out = _render("map-pin", "San Francisco")
    assert "</i>San Francisco" in out
    assert "</i> San Francisco" not in out
    assert "</i>\n" not in out.split("San Francisco")[0].rsplit("</i>", 1)[0] + "</i>"


def test_icon_label_carries_aria_hidden_on_the_icon() -> None:
    """The icon is decorative — the adjacent label carries the accessible
    name. Standardizing on ``aria-hidden="true"`` here means call sites don't
    have to remember to set it."""
    out = _render("shield", "Aetna")
    assert 'aria-hidden="true"' in out


def test_icon_label_icon_param_is_glyph_name_without_prefix() -> None:
    """Caller passes ``"chevron-left"``, not ``"icon-chevron-left"``."""
    out = _render("chevron-left", "Prev")
    assert 'class="icon-chevron-left"' in out
    assert "icon-icon-" not in out


def test_icon_label_label_may_contain_special_chars_and_is_escaped() -> None:
    out = _render("layers", "Outpatient & IOP")
    assert "Outpatient &amp; IOP" in out
