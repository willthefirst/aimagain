"""Tests for the pagination primitives.

The framework's list dispatcher and bespoke list handlers both compose
`parse_page` + `paginate(...)` to expose a `Page` snapshot to the
template. These tests pin the behavior independently of any handler.
"""

from __future__ import annotations

from starlette.requests import Request

from src.framework.dispatch.pagination import (
    DEFAULT_PAGE_SIZE,
    Page,
    offset_for,
    paginate,
    parse_page,
)


def _request_with_query(query: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": query.encode(),
        "headers": [],
    }
    return Request(scope)


def test_parse_page_defaults_to_one_when_absent() -> None:
    assert parse_page(_request_with_query("")) == 1


def test_parse_page_reads_integer_value() -> None:
    assert parse_page(_request_with_query("page=3")) == 3


def test_parse_page_clamps_zero_to_one() -> None:
    assert parse_page(_request_with_query("page=0")) == 1


def test_parse_page_clamps_negative_to_one() -> None:
    assert parse_page(_request_with_query("page=-5")) == 1


def test_parse_page_defaults_on_non_integer() -> None:
    """Bad input is a stale-link symptom, not a request-time fault.
    Defaulting to page 1 keeps the rest of the URL (filters, etc.)
    meaningful instead of 422-ing the whole render."""
    assert parse_page(_request_with_query("page=abc")) == 1


def test_offset_for_first_page_is_zero() -> None:
    assert offset_for(1, 25) == 0


def test_offset_for_third_page_with_default_size() -> None:
    assert offset_for(3, DEFAULT_PAGE_SIZE) == 30


def test_paginate_full_page_with_overflow_signals_has_next() -> None:
    """The handler probes `per_page + 1` rows; if the layer returned
    that many, the next page exists and the trailing probe is sliced
    off before the items reach the template."""
    probe = list(range(26))  # per_page=25, +1 probe row
    items, page_meta = paginate(probe, page=1, per_page=25)
    assert items == list(range(25))
    assert page_meta.has_next is True
    assert page_meta.has_prev is False


def test_paginate_exact_page_size_means_no_next() -> None:
    """If the layer returned exactly `per_page` rows the probe is
    missing — this is the last page even though it's full."""
    probe = list(range(25))
    items, page_meta = paginate(probe, page=2, per_page=25)
    assert items == list(range(25))
    assert page_meta.has_next is False
    assert page_meta.has_prev is True


def test_paginate_short_page_means_no_next() -> None:
    probe = list(range(10))
    items, page_meta = paginate(probe, page=1, per_page=25)
    assert items == list(range(10))
    assert page_meta.has_next is False
    assert page_meta.has_prev is False


def test_paginate_empty_page_two_still_has_prev() -> None:
    """A user landing on `?page=99` for a 1-page list sees 'Prev'
    so they can navigate back rather than getting stuck."""
    items, page_meta = paginate([], page=99, per_page=25)
    assert items == []
    assert page_meta.has_next is False
    assert page_meta.has_prev is True


def test_page_next_and_prev_numbers() -> None:
    page = Page(page=3, per_page=25, has_prev=True, has_next=True)
    assert page.prev_page == 2
    assert page.next_page == 4


def test_page_prev_clamps_at_one() -> None:
    page = Page(page=1, per_page=25, has_prev=False, has_next=True)
    assert page.prev_page == 1


def test_pager_bundles_page_and_base_query() -> None:
    """``Pager`` is a frozen bundle of ``Page`` + base query string so
    templates receive pagination state as one argument rather than two."""
    from src.framework.dispatch.pagination import Pager

    page = Page(page=2, per_page=15, has_prev=True, has_next=False)
    pager = Pager(page=page, base_query="kind=referral")
    assert pager.page is page
    assert pager.base_query == "kind=referral"


def test_pager_defaults_base_query_to_empty() -> None:
    from src.framework.dispatch.pagination import Pager

    page = Page(page=1, per_page=15, has_prev=False, has_next=False)
    pager = Pager(page=page)
    assert pager.base_query == ""
