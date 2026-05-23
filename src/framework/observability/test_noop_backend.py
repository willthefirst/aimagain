"""Tests for `noop_backend.py`.

The Noop backend's contract is "doesn't crash, returns the sentinel
shape" — that's exactly what we verify here.
"""

from fastapi import FastAPI

from .noop_backend import NoopBackend


def test_init_app_is_noop():
    backend = NoopBackend()
    # Must not raise on a real FastAPI instance — call sites pass `app`
    # unconditionally and the Noop branch has to absorb it.
    backend.init_app(FastAPI())


def test_set_user_is_noop():
    backend = NoopBackend()
    backend.set_user("abc", "user@example.com")
    backend.set_user("abc", None)


def test_frontend_context_returns_none():
    """`None` is the signal `base.html` reads to skip the browser SDK
    `<script>` block entirely."""
    assert NoopBackend().frontend_context() is None
