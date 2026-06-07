"""Tests for the pagination macro in ``_shared/pagination.html``.

Pins the structural contract: when to emit the nav, which icons appear,
which links are active vs disabled, and rel attributes — so a refactor
can't silently break the rendered output.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser

from src.framework.dispatch.pagination import Page


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(str(Path(__file__).resolve().parents[1]))
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(page: Page, base_query: str = "") -> str:
    snippet = textwrap.dedent(f"""\
        {{%- from "_shared/pagination.html" import pagination -%}}
        {{{{ pagination(page_meta, {base_query!r}) }}}}
        """)
    return _make_env().from_string(snippet).render(page_meta=page)


def _page(**kwargs) -> Page:
    defaults = dict(page=1, per_page=15, has_prev=False, has_next=False)
    return Page(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


def test_single_page_emits_nothing() -> None:
    assert _render(_page(has_prev=False, has_next=False)).strip() == ""


def test_emits_nav_when_has_prev() -> None:
    html = _render(_page(page=2, has_prev=True))
    assert HTMLParser(html).css_first("nav") is not None


def test_emits_nav_when_has_next() -> None:
    html = _render(_page(has_next=True))
    assert HTMLParser(html).css_first("nav") is not None


# ---------------------------------------------------------------------------
# CSS class for centering
# ---------------------------------------------------------------------------


def test_nav_carries_pagination_nav_class() -> None:
    html = _render(_page(has_next=True))
    nav = HTMLParser(html).css_first("nav")
    assert nav is not None
    assert "pagination-nav" in (nav.attributes.get("class") or "")


# ---------------------------------------------------------------------------
# Lucide chevron icons
# ---------------------------------------------------------------------------


def test_prev_link_has_chevron_left_icon() -> None:
    html = _render(_page(page=2, has_prev=True))
    prev_link = HTMLParser(html).css_first("a[rel='prev']")
    assert prev_link is not None
    assert prev_link.css_first("i.icon-chevron-left") is not None


def test_prev_disabled_has_chevron_left_icon() -> None:
    html = _render(_page(has_next=True))
    disabled = HTMLParser(html).css_first("span[aria-disabled='true']")
    assert disabled is not None
    assert disabled.css_first("i.icon-chevron-left") is not None


def test_next_link_has_chevron_right_icon() -> None:
    html = _render(_page(has_next=True))
    next_link = HTMLParser(html).css_first("a[rel='next']")
    assert next_link is not None
    assert next_link.css_first("i.icon-chevron-right") is not None


def test_next_disabled_has_chevron_right_icon() -> None:
    html = _render(_page(page=2, has_prev=True))
    # last li span is the disabled next
    disabled_spans = HTMLParser(html).css("span[aria-disabled='true']")
    assert any(s.css_first("i.icon-chevron-right") for s in disabled_spans)


def test_no_guillemet_entities_in_output() -> None:
    html = _render(_page(page=2, has_prev=True, has_next=True))
    assert "«" not in html
    assert "»" not in html
    assert "&laquo;" not in html
    assert "&raquo;" not in html


# ---------------------------------------------------------------------------
# Links and rel attributes
# ---------------------------------------------------------------------------


def test_prev_link_points_to_previous_page() -> None:
    html = _render(_page(page=3, has_prev=True))
    a = HTMLParser(html).css_first("a[rel='prev']")
    assert a is not None
    assert "page=2" in (a.attributes.get("href") or "")


def test_next_link_points_to_next_page() -> None:
    html = _render(_page(page=1, has_next=True))
    a = HTMLParser(html).css_first("a[rel='next']")
    assert a is not None
    assert "page=2" in (a.attributes.get("href") or "")


def test_base_query_preserved_in_prev_link() -> None:
    html = _render(_page(page=2, has_prev=True), base_query="kind=referral")
    a = HTMLParser(html).css_first("a[rel='prev']")
    assert a is not None
    href = a.attributes.get("href") or ""
    assert "kind=referral" in href
    assert "page=1" in href


def test_base_query_preserved_in_next_link() -> None:
    html = _render(_page(page=1, has_next=True), base_query="kind=referral")
    a = HTMLParser(html).css_first("a[rel='next']")
    assert a is not None
    href = a.attributes.get("href") or ""
    assert "kind=referral" in href
    assert "page=2" in href


def test_current_page_number_shown() -> None:
    html = _render(_page(page=5, has_next=True))
    span = HTMLParser(html).css_first("span[aria-current='page']")
    assert span is not None
    assert "5" in span.text()
