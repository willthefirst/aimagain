"""Tests for `base.html` — the document-shell template every page extends.

These pin contracts that live on the `<head>` itself (not on a particular
view-type chrome): the head scripts must not render-block the initial
paint. `_page_header.html` band tests live in `test_page_header.py`;
view-type chrome tests live in `test_views.py`.
"""

from __future__ import annotations

from jinja2 import Environment
from selectolax.parser import HTMLParser

from src.framework.templates._test_env import add_child as _add_child
from src.framework.templates._test_env import make_test_env as _make_env_impl


def _make_env() -> Environment:
    return _make_env_impl()


class _RequestStub:
    class _Url:
        path = "/"

    url = _Url()
    query_params: dict[str, str] = {}


def _request_stub() -> _RequestStub:
    return _RequestStub()


_STUB = """
    {% extends "base.html" %}
    {% block content %}<p>body</p>{% endblock %}
"""


def _render(observability_frontend: object | None = None) -> str:
    env = _make_env()
    _add_child(env, "stub.html", _STUB)
    return env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        observability_frontend=observability_frontend,
    )


_SENTRY_FRONTEND = {
    "provider": "sentry",
    "dsn": "https://example@sentry.io/1",
    "environment": "test",
    "release": "abc123",
    "traces_sample_rate": 0.1,
    "replays_session_sample_rate": 0.0,
    "replays_on_error_sample_rate": 0.0,
}


def test_head_scripts_carry_defer_so_first_paint_is_not_render_blocked() -> None:
    """Every external `<script src=...>` inside `<head>` must declare
    `defer` (or `async`) — otherwise the parser blocks while the
    script downloads + executes, delaying first paint on every page.

    htmx attaches its initial DOM scan to `DOMContentLoaded`, so
    `defer` is the supported pattern: scripts run in document order
    after parsing completes but before that event fires.

    Asserted under both the no-observability render AND the
    sentry-on render — the Sentry loader is a separate render-blocking
    surface gated by `observability_frontend`.

    See https://developer.chrome.com/docs/performance/insights/render-blocking.
    """
    for label, frontend in (("no observability", None), ("sentry", _SENTRY_FRONTEND)):
        html = _render(frontend)
        tree = HTMLParser(html)
        head = tree.css_first("head")
        assert head is not None

        offenders = [
            node.attributes.get("src")
            for node in head.css("script")
            if node.attributes.get("src")
            and "defer" not in node.attributes
            and "async" not in node.attributes
        ]
        assert not offenders, (
            f"[{label}] head scripts missing defer/async (each adds "
            f"render-blocking latency to every page): {offenders}"
        )


def test_meta_description_present_with_default_copy() -> None:
    """`base.html` always emits `<meta name="description">`. Without
    it, search engines and link-preview crawlers fall back to the
    first sentence of the body — usually nav chrome on this app. The
    default sentence applies to every page that doesn't override the
    `meta_description` block.
    """
    tree = HTMLParser(_render())
    descriptions = [
        node
        for node in tree.css("meta")
        if node.attributes.get("name") == "description"
    ]
    assert len(descriptions) == 1
    content = descriptions[0].attributes.get("content") or ""
    assert "Bedlam Connect" in content
    assert len(content) > 30


def test_preconnect_to_each_vendor_cdn() -> None:
    """Every cross-origin CDN we fetch from in `<head>` needs a
    matching `<link rel="preconnect">` so the TCP+TLS handshake fires
    in parallel with HTML parsing — otherwise the first request to
    that origin pays the full RTT serially.

    Currently three: Pico (jsdelivr), htmx + extensions (unpkg),
    Sentry SDK (sentry-cdn).
    """
    tree = HTMLParser(_render())
    preconnects = {
        node.attributes.get("href") for node in tree.css('link[rel="preconnect"]')
    }
    assert "https://cdn.jsdelivr.net" in preconnects
    assert "https://unpkg.com" in preconnects
    assert "https://browser.sentry-cdn.com" in preconnects


def test_sentry_bundle_picks_non_tracing_when_traces_disabled() -> None:
    """`traces_sample_rate=0` means we don't need
    `Sentry.browserTracingIntegration()` — and that integration only
    ships in the `bundle.tracing.*` builds (~14 KiB larger). The
    template must drop to `bundle.min.js` in that case (or
    `bundle.replay.min.js` when replays are enabled).
    """
    no_traces = {**_SENTRY_FRONTEND, "traces_sample_rate": 0.0}
    tree = HTMLParser(_render(no_traces))
    srcs = [node.attributes.get("src", "") for node in tree.css("script")]
    sentry_srcs = [s for s in srcs if "sentry-cdn.com" in s]
    assert len(sentry_srcs) == 1
    assert "/bundle.min.js" in sentry_srcs[0]
    assert "tracing" not in sentry_srcs[0]

    traces_on = {**_SENTRY_FRONTEND, "traces_sample_rate": 0.1}
    tree = HTMLParser(_render(traces_on))
    sentry_srcs = [
        s
        for s in (n.attributes.get("src", "") for n in tree.css("script"))
        if "sentry-cdn.com" in s
    ]
    assert "/bundle.tracing.min.js" in sentry_srcs[0]
