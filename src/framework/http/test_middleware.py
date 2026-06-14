"""Tests for `src/framework/http/middleware.py`."""

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from .middleware import (
    StaticLongCacheMiddleware,
    StaticNoCacheMiddleware,
    _strip_empty_pairs,
)


def _make_client(middleware_cls) -> TestClient:
    app = FastAPI()
    app.add_middleware(middleware_cls)

    @app.get("/static/fw/css/framework.css")
    def static_css():
        return PlainTextResponse("body{}")

    @app.get("/page")
    def page():
        return PlainTextResponse("hi")

    return TestClient(app)


def test_static_path_gets_no_store():
    client = _make_client(StaticNoCacheMiddleware)
    r = client.get("/static/fw/css/framework.css")
    assert r.headers["cache-control"] == "no-store"


def test_non_static_path_unaffected():
    client = _make_client(StaticNoCacheMiddleware)
    r = client.get("/page")
    assert "cache-control" not in r.headers


def test_long_cache_versioned_url_is_immutable():
    """`?v=...` is the sentinel that a static URL came from a
    template render using `static_version` — i.e. the URL itself
    encodes the deploy SHA and so the bytes will not change. Safe to
    cache for a year with `immutable`."""
    client = _make_client(StaticLongCacheMiddleware)
    r = client.get("/static/fw/css/framework.css?v=abc123")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_long_cache_unversioned_url_is_short_revalidate():
    """No `?v=` → can't tell whether bytes are stable. Short TTL +
    `must-revalidate` so a deploy of new contents lands within ~5
    minutes; ETag-driven 304s keep the wire cost near zero on
    revalidating hits."""
    client = _make_client(StaticLongCacheMiddleware)
    r = client.get("/static/fw/css/framework.css")
    assert r.headers["cache-control"] == "public, max-age=300, must-revalidate"


def test_long_cache_skips_non_static_paths():
    client = _make_client(StaticLongCacheMiddleware)
    r = client.get("/page")
    assert "cache-control" not in r.headers


def test_strip_empty_value():
    assert _strip_empty_pairs(b"x=") == b""


def test_strip_keeps_non_empty():
    assert _strip_empty_pairs(b"x=1") == b"x=1"


def test_strip_mixed_keeps_only_non_empty():
    assert _strip_empty_pairs(b"a=&b=2&c=") == b"b=2"


def test_strip_keeps_whitespace_value():
    """`%20` is an encoded space — a real value, not empty."""
    assert _strip_empty_pairs(b"x=%20") == b"x=%20"


def test_strip_flag_style_no_equals():
    """`?key` with no `=` has no value; treat as absent."""
    assert _strip_empty_pairs(b"flag") == b""


def test_strip_keeps_value_containing_equals():
    """`x=a=b` has value `a=b`; only the FIRST `=` separates name and value."""
    assert _strip_empty_pairs(b"x=a=b") == b"x=a=b"


def test_strip_collapses_repeated_ampersands():
    assert _strip_empty_pairs(b"a=1&&b=2") == b"a=1&b=2"


def test_strip_repeated_key_keeps_non_empty_instances():
    assert _strip_empty_pairs(b"x=a&x=&x=b") == b"x=a&x=b"


def test_strip_empty_input_returns_empty():
    assert _strip_empty_pairs(b"") == b""
