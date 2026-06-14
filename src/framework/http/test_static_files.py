"""Tests for `MinifyingStaticFiles` + the `minify_css` helper."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .static_files import MinifyingStaticFiles, minify_css


def test_minify_strips_comments_and_collapses_whitespace():
    src = """
        /* header rule */
        body {
            color: red;
            margin: 0;
        }
    """
    out = minify_css(src)
    assert "/*" not in out
    assert "header rule" not in out
    # The "compact" form survives but the long whitespace runs do not.
    assert "body{color:red;margin:0}" in out


def test_minify_drops_trailing_semicolon_before_brace():
    src = "a { x: 1; y: 2; }"
    out = minify_css(src)
    assert out.endswith("y:2}")


def test_minify_preserves_multiple_rules():
    src = ".a{color:red}.b{color:blue}"
    assert minify_css(src) == ".a{color:red}.b{color:blue}"


def test_minify_collapses_around_combinators_and_commas():
    src = ".a    >    .b ,  .c   {   color: red; }"
    out = minify_css(src)
    assert out == ".a>.b,.c{color:red}"


@pytest.fixture
def static_dir():
    with tempfile.TemporaryDirectory() as d:
        css_path = os.path.join(d, "styles.css")
        with open(css_path, "w") as f:
            f.write("/* drop me */\nbody  {  color:  red;  }\n")
        bin_path = os.path.join(d, "blob.txt")
        with open(bin_path, "w") as f:
            f.write("hello world\n")
        yield d


def _client(static_dir: str) -> TestClient:
    app = FastAPI()
    app.mount("/static", MinifyingStaticFiles(directory=static_dir))
    return TestClient(app)


def test_css_response_is_minified(static_dir: str):
    r = _client(static_dir).get("/static/styles.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    body = r.text
    assert "/*" not in body
    assert "drop me" not in body
    assert "body{color:red}" in body


def test_non_css_response_unchanged(static_dir: str):
    r = _client(static_dir).get("/static/blob.txt")
    assert r.status_code == 200
    assert r.text == "hello world\n"


def test_css_response_carries_weak_etag(static_dir: str):
    r = _client(static_dir).get("/static/styles.css")
    etag = r.headers["etag"]
    assert etag.startswith('W/"')


def test_if_none_match_returns_304(static_dir: str):
    client = _client(static_dir)
    r1 = client.get("/static/styles.css")
    etag = r1.headers["etag"]
    r2 = client.get("/static/styles.css", headers={"if-none-match": etag})
    assert r2.status_code == 304
    assert r2.headers["etag"] == etag


def test_minified_bytes_cached_after_first_request(static_dir: str):
    """The cache lives on the StaticFiles instance — a second request
    on the same client / app instance must not re-read the file. Asserted
    by comparing object identity of the cache value across two calls."""
    files = MinifyingStaticFiles(directory=static_dir)
    app = FastAPI()
    app.mount("/static", files)
    client = TestClient(app)
    client.get("/static/styles.css")
    assert "styles.css" in files._css_cache
    cached_before = files._css_cache["styles.css"]
    client.get("/static/styles.css")
    assert files._css_cache["styles.css"] is cached_before
