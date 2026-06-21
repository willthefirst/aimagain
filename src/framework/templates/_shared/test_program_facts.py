"""Tests for `_shared/_program_facts.html`.

`program_facts(program)` is the single home for rendering a `Program`'s
steady-state context as `fact(...)` rows — now just `website` and
`referral_instructions` (the per-announcement profile moved onto the
intake post). The program detail page (and any post surface showing the
same context) composes this macro; these tests pin the row keys, the
website-link treatment, and the empty-suppression contract.
"""

from __future__ import annotations

from types import SimpleNamespace

from selectolax.parser import HTMLParser

from src.framework.templates._test_env import make_test_env

_TEMPLATE = (
    '{%- from "_shared/sections.html" import facts_block -%}'
    '{%- from "_shared/_program_facts.html" import program_facts -%}'
    "{% call facts_block() %}{{ program_facts(program) }}{% endcall %}"
)


def _render(program) -> HTMLParser:
    env = make_test_env()
    return HTMLParser(env.from_string(_TEMPLATE).render(program=program))


def _full_program() -> SimpleNamespace:
    return SimpleNamespace(
        website="https://program.example.org",
        referral_instructions="Email intake@program.example.org.",
    )


def _empty_program() -> SimpleNamespace:
    return SimpleNamespace(
        website=None,
        referral_instructions=None,
    )


def test_full_profile_renders_every_row_by_stable_key() -> None:
    tree = _render(_full_program())
    keys = [row.attributes.get("data-fact") for row in tree.css("div[data-fact]")]
    assert keys == [
        "website",
        "referral_instructions",
    ]


def test_rows_carry_referral_instructions_and_website_link() -> None:
    tree = _render(_full_program())
    html = tree.html or ""
    assert "Email intake@program.example.org." in html
    link = tree.css_first('div[data-fact="website"] a')
    assert link is not None
    assert link.attributes.get("href") == "https://program.example.org"
    assert link.attributes.get("target") == "_blank"


def test_empty_profile_suppresses_every_row() -> None:
    tree = _render(_empty_program())
    assert tree.css("div[data-fact]") == []
