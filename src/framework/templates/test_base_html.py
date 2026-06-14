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


def test_head_scripts_carry_defer_so_first_paint_is_not_render_blocked() -> None:
    """Every external `<script src=...>` inside `<head>` must declare
    `defer` (or `async`) — otherwise the parser blocks while the
    script downloads + executes, delaying first paint on every page.

    htmx attaches its initial DOM scan to `DOMContentLoaded`, so
    `defer` is the supported pattern: scripts run in document order
    after parsing completes but before that event fires.

    See https://developer.chrome.com/docs/performance/insights/render-blocking.
    """
    env = _make_env()
    _add_child(env, "stub.html", _STUB)
    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
        observability_frontend=None,
    )

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
        "Head scripts missing defer/async (each adds render-blocking "
        f"latency to every page): {offenders}"
    )
