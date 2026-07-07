"""Tests for the ``_shared/_breadcrumb.html`` macro.

The breadcrumb renders a full Pico chain: a "Home" root (→ `/`, the
single home entry point) prepended to each passed
``(label, href, lock_reason?)`` segment, with Pico drawing the ``>``
dividers. Per segment:

  - ``lock_reason`` set (a closed-vocab ``REASON_*`` code) → a
    ``data-locked-cta`` popover trigger with NO ``href``, so the visible link
    can't disagree with the destination page's ``read_policy.assert_can_read``.
  - ``href`` set, no lock → a plain ``<a href>`` link.
  - neither → plain current-page text (``aria-current="page"``).
"""

from __future__ import annotations

import textwrap

from jinja2 import Environment
from selectolax.parser import HTMLParser, Node

from src.domain.logic import capabilities
from src.framework.templates._test_env import make_test_env


def _make_env() -> Environment:
    return make_test_env()


def _render(items_literal: str) -> str:
    """Render the breadcrumb macro with the given Python tuple-list literal."""
    snippet = textwrap.dedent(f"""\
        {{%- from "_shared/_breadcrumb.html" import breadcrumb -%}}
        {{{{ breadcrumb({items_literal}) }}}}
        """)
    return _make_env().from_string(snippet).render()


def _crumbs(html: str) -> list[Node]:
    return HTMLParser(html).css("nav[aria-label='breadcrumb'] ul li")


def test_home_root_is_always_prepended() -> None:
    """Every chain starts with a Home link to `/` — an empty `items`
    renders just that crumb."""
    lis = _crumbs(_render("[]"))
    assert len(lis) == 1
    home = lis[0].css_first("a")
    assert home.text(strip=True) == "Home"
    assert home.attributes.get("href") == "/"


def test_two_tuple_segment_renders_link_after_home() -> None:
    """Legacy 2-tuple shape (label, href) renders a plain `<a>` link, after
    the Home root."""
    lis = _crumbs(_render('[("Posts", "/posts")]'))
    assert [li.text(strip=True) for li in lis] == ["Home", "Posts"]
    a = lis[1].css_first("a")
    assert a.attributes.get("href") == "/posts"
    assert "data-locked-cta" not in a.attributes


def test_three_tuple_no_reason_renders_link() -> None:
    """3-tuple with `lock_reason=None` is identical to the 2-tuple case."""
    a = _crumbs(_render('[("Posts", "/posts", none)]'))[1].css_first("a")
    assert a.attributes.get("href") == "/posts"
    assert "data-locked-cta" not in a.attributes


def test_hrefless_segment_is_the_current_page() -> None:
    """A segment with `href=None` is the current page — plain text with
    `aria-current="page"`, no link."""
    current = _crumbs(_render('[("Clinicians", none)]'))[1]
    assert current.css_first("a") is None
    span = current.css_first("span")
    assert span.text(strip=True) == "Clinicians"
    assert span.attributes.get("aria-current") == "page"


def test_lock_reason_renders_locked_trigger_with_no_href() -> None:
    """A segment with a `REASON_*` code emits the popover-trigger chrome:
    aria-disabled, `data-locked-cta`, and crucially no `href` so a click
    can't navigate to the gated page."""
    a = _crumbs(
        _render('[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER)]')
    )[1].css_first("a")
    assert a.attributes.get("aria-disabled") == "true"
    assert (
        a.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    assert "href" not in a.attributes
    assert a.text(strip=True) == "Users"


def test_full_chain_renders_every_segment_in_order() -> None:
    """A multi-segment chain renders Home + each segment in order; ancestors
    with an href link, the trailing href-less segment is the current page."""
    lis = _crumbs(
        _render(
            '[("Clinicians", "/clinicians"),'
            ' ("Maya Ellis", "/clinicians/abc"),'
            ' ("Edit", none)]'
        )
    )
    assert [li.text(strip=True) for li in lis] == [
        "Home",
        "Clinicians",
        "Maya Ellis",
        "Edit",
    ]
    assert lis[1].css_first("a").attributes.get("href") == "/clinicians"
    assert lis[2].css_first("a").attributes.get("href") == "/clinicians/abc"
    assert lis[3].css_first("a") is None
    assert lis[3].css_first("span").attributes.get("aria-current") == "page"


def test_lock_is_per_segment() -> None:
    """A lock on one ancestor locks only that crumb; the others render
    normally — each link respects its own read gate."""
    lis = _crumbs(
        _render(
            '[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER),'
            ' ("Will", "/users/abc", none),'
            ' ("Favorites", none, none)]'
        )
    )
    users = lis[1].css_first("a")
    assert (
        users.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    assert "href" not in users.attributes
    assert lis[2].css_first("a").attributes.get("href") == "/users/abc"
    assert lis[3].css_first("span").attributes.get("aria-current") == "page"
