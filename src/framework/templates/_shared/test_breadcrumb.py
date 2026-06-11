"""Tests for the ``_shared/_breadcrumb.html`` macro.

The breadcrumb renders the deepest clickable parent as the "back"
affordance. Each item is a ``(label, href, lock_reason)`` tuple — the
third element is optional and, when set to a closed-vocab ``REASON_*``
code, switches the back link to a locked popover-trigger instead of a
plain ``<a>``. That branch is what keeps the visible link consistent
with the destination page's ``read_policy.assert_can_read`` — without
it, clicking the back link from ``/users/me`` lands on a 403.
"""

from __future__ import annotations

import textwrap

from jinja2 import Environment
from selectolax.parser import HTMLParser

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


def test_breadcrumb_two_tuple_back_link_renders_anchor() -> None:
    """Legacy 2-tuple shape (label, href) still renders a plain `<a>`."""
    html = _render('[("Posts", "/posts")]')
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    assert a.attributes.get("href") == "/posts"
    assert "data-locked-cta" not in a.attributes


def test_breadcrumb_three_tuple_no_reason_renders_anchor() -> None:
    """3-tuple with `lock_reason=None` is identical to the 2-tuple case."""
    html = _render('[("Posts", "/posts", none)]')
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    assert a.attributes.get("href") == "/posts"
    assert "data-locked-cta" not in a.attributes


def test_breadcrumb_lock_reason_set_renders_locked_back() -> None:
    """3-tuple with a `REASON_*` code emits the popover-trigger chrome:
    aria-disabled, `data-locked-cta`, and crucially no `href` so a click
    can't navigate to the gated page."""
    html = _render('[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER)]')
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    assert a.attributes.get("aria-disabled") == "true"
    assert (
        a.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    assert "href" not in a.attributes
    assert a.css_first("span.breadcrumb-back-label").text() == "Users"


def test_breadcrumb_lock_reason_preserves_chevron() -> None:
    """The locked branch keeps the back-chevron icon — visual continuity
    with the normal breadcrumb-back so the layout doesn't shift."""
    html = _render('[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER)]')
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    assert a.css_first("i.icon-arrow-left") is not None


def test_breadcrumb_multi_segment_uses_deepest_linkable_for_lock() -> None:
    """For nested chains, the back target is the deepest item with an href
    — when that item carries a lock_reason, the back link is locked."""
    html = _render(
        '[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER),'
        ' ("Will", "/users/abc", none),'
        ' ("Favorites", none, none)]'
    )
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    # Back target is the parent row link (/users/abc), which has no lock
    # — so the rendered link is a plain anchor.
    assert a.attributes.get("href") == "/users/abc"
    assert "data-locked-cta" not in a.attributes


def test_breadcrumb_two_segment_locks_when_collection_locked() -> None:
    """On a subresource list (`/users/me/favorites`) where the parent row
    is the current page, the back target IS the collection — locking
    propagates to the visible link."""
    html = _render(
        '[("Users", "/users", capabilities.REASON_NOT_A_VERIFIED_PROVIDER),'
        ' ("Favorites", none, none)]'
    )
    a = HTMLParser(html).css_first("a.breadcrumb-back")
    assert a is not None
    assert (
        a.attributes.get("data-locked-cta")
        == capabilities.REASON_NOT_A_VERIFIED_PROVIDER
    )
    assert "href" not in a.attributes
