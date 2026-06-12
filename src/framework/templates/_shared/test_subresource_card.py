"""Tests for the ``subresource_card`` macro in ``_shared/_card.html``.

The macro is the declarative wrapper around ``card`` + ``facts_block`` + ``fact``
that the clinician credential lists (certifications, licensures, educations) use.
It exists to keep those three lists from re-emitting the same headline / subtitle
/ facts skeleton; each test below pins a single shape contract so a future
refactor can't silently regress one credential's list rendering.
"""

from __future__ import annotations

import textwrap

from src.framework.templates._test_env import make_test_env


def _render(call: str) -> str:
    return make_test_env().from_string(textwrap.dedent(f"""\
        {{%- from "_shared/_card.html" import subresource_card -%}}
        {call}
        """)).render()


def test_renders_card_article_with_headline_link() -> None:
    out = _render(
        '{{ subresource_card(id=42, headline_url="/x/42/form",'
        ' headline="License XYZ") }}'
    )
    assert 'data-row-id="42"' in out
    assert '<a href="/x/42/form">License XYZ</a>' in out


def test_subtitle_parts_wrap_each_truthy_string_in_span() -> None:
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' subtitle_parts=["CA", "Active"]) }}'
    )
    assert "<span>CA</span>" in out
    assert "<span>Active</span>" in out


def test_subtitle_parts_skip_falsy_entries() -> None:
    """An empty / None entry leaves no `<span></span>` hole."""
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' subtitle_parts=[None, "Only one", ""]) }}'
    )
    assert "<span>Only one</span>" in out
    assert "<span></span>" not in out


def test_subtitle_omitted_when_no_parts_render() -> None:
    """All-empty `subtitle_parts` produces no `<small class="meta">` band."""
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' subtitle_parts=[None, ""]) }}'
    )
    assert 'class="meta"' not in out


def test_facts_render_inside_facts_block_with_data_fact_keys() -> None:
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' facts=[("expiration_date", "Expires", "2030-01-01")]) }}'
    )
    assert 'class="entity-facts"' in out
    assert 'data-fact="expiration_date"' in out
    assert "Expires" in out
    assert "2030-01-01" in out


def test_facts_with_falsy_values_are_skipped() -> None:
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' facts=[("a", "A", None), ("b", "B", ""), ("c", "C", "kept")]) }}'
    )
    assert 'data-fact="a"' not in out
    assert 'data-fact="b"' not in out
    assert 'data-fact="c"' in out
    assert "kept" in out


def test_facts_block_omitted_entirely_when_every_value_is_falsy() -> None:
    """The 'no surfaced facts' branch — used by certification/education rows
    whose only optional fact (expiration_date / month_completed) is unset."""
    out = _render(
        '{{ subresource_card(id=1, headline_url="/x", headline="H",'
        ' facts=[("a", "A", None)]) }}'
    )
    assert 'class="entity-facts"' not in out


def test_works_with_no_subtitle_or_facts_args() -> None:
    """Minimal call — just the card chrome and the headline link."""
    out = _render('{{ subresource_card(id=1, headline_url="/x", headline="H") }}')
    assert 'data-row-id="1"' in out
    assert '<a href="/x">H</a>' in out
    assert 'class="meta"' not in out
    assert 'class="entity-facts"' not in out
