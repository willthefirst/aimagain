"""Coverage for `posts_url_for_filters` — the saved-search → `/posts?…`
render (the "open" half of the round-trip)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from src.domain.logic.saved_searches.urls import POSTS_PATH, posts_url_for_filters


def test_empty_filters_render_bare_posts_path():
    assert posts_url_for_filters({}) == POSTS_PATH
    assert posts_url_for_filters(None) == POSTS_PATH


def test_scalar_filter_renders_single_param():
    assert posts_url_for_filters({"kind": "clinician_opening"}) == (
        "/posts?kind=clinician_opening"
    )


def test_multi_value_filter_repeats_param():
    url = posts_url_for_filters({"state": ["CA", "NY"]})
    qs = parse_qs(urlsplit(url).query)
    assert qs["state"] == ["CA", "NY"]


def test_empty_and_none_values_are_dropped():
    url = posts_url_for_filters(
        {"kind": "referral", "q": "", "state": [], "city": None}
    )
    qs = parse_qs(urlsplit(url).query)
    assert qs == {"kind": ["referral"]}


def test_roundtrips_through_posts_query_parser_shape():
    """The rendered query string parses back to the same logical
    filter set the `/posts` list would receive."""
    filters = {"kind": "clinician_opening", "state": ["CA", "NY"], "q": "trauma"}
    qs = parse_qs(urlsplit(posts_url_for_filters(filters)).query)
    assert qs == {"kind": ["clinician_opening"], "state": ["CA", "NY"], "q": ["trauma"]}
