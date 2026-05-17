"""Tests for the generic view-type templates in ``src/framework/templates/views/``.

These templates wire the page chrome (breadcrumb + toolbar + content) by
convention so a domain template only declares what's unique to it. The
tests below pin the chrome contract by rendering each view-type template
with stub child templates and asserting the breadcrumb segments, toolbar
shape, and content block all land where the contract promises.

Domain-template-side coverage lives in the route tests (e.g.
``src/domain/routes/test_providers.py``); these tests cover the
view-type templates *in isolation* so a regression in the chrome shows
up here even if no domain template has been wired into it yet.
"""

from __future__ import annotations

import textwrap

from jinja2 import DictLoader, Environment, FileSystemLoader, select_autoescape
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    """Stand up a Jinja env layered over the framework templates root
    plus an in-memory dict loader for the child stubs each test defines.

    Uses ``ChoiceLoader`` semantics via two ``FileSystemLoader``s? No —
    Jinja's ``Environment`` only takes one loader. The dict loader for
    the stubs goes first; framework templates resolve through the
    fallback ``FileSystemLoader``. This is identical to how the real
    runtime resolves ``views/...`` from the framework root and
    ``providers/list.html`` from the domain root.
    """
    from jinja2 import ChoiceLoader

    framework_loader = FileSystemLoader("src/framework/templates")
    # Per-test stub child templates go in the DictLoader the caller
    # populates via ``env.loader.loaders[0].mapping[...]``.
    stub_loader = DictLoader({})
    env = Environment(
        loader=ChoiceLoader([stub_loader, framework_loader]),
        autoescape=select_autoescape(["html", "xml"]),
    )
    # The shared `_toolbar.html` / `_breadcrumb.html` macros render
    # `breadcrumb(items)` which is pure HTML and needs no globals; no
    # context wiring required for these tests.
    return env


def _add_child(env: Environment, name: str, body: str) -> None:
    env.loader.loaders[0].mapping[name] = textwrap.dedent(body).lstrip()


def test_list_view_renders_single_segment_breadcrumb() -> None:
    """``views/list.html`` fills the `breadcrumb` block with a
    single-segment `breadcrumb([(resource_label, None)])` call. The
    child only declares the label."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Providers{% endblock %}
        {% block content %}<div id="body">ok</div>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    # Single-segment breadcrumb: the label appears inside the
    # `<nav aria-label="breadcrumb">` strip with `aria-current="page"`
    # (no `<a>` for the trailing segment).
    assert 'aria-label="breadcrumb"' in html
    assert 'aria-current="page"' in html
    assert "Providers" in html
    # Content block lands in the page body.
    assert '<div id="body">ok</div>' in html


def test_list_view_omits_toolbar_when_no_filters_no_actions() -> None:
    """The toolbar shell renders only when filters or actions are
    present — empty pages don't emit a stray `<hr />`."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Users{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    # Parse rather than substring-match: `base.html`'s CSS comment
    # references `<div class="toolbar">` verbatim to document the
    # shape, so a naive `in html` check would false-positive.
    tree = HTMLParser(html)
    assert tree.css_first("div.toolbar") is None


def test_list_view_renders_actions_block_in_toolbar_right() -> None:
    """A child that fills `{% block actions %}` gets its content in the
    toolbar's right zone, which is a `<menu>` of `<li>` commands."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/list.html" %}
        {% block resource_label %}Posts{% endblock %}
        {% block actions %}<li><a id="create" href="/posts/form">Create</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    assert '<li><a id="create" href="/posts/form">Create</a></li>' in html


def test_detail_view_renders_two_segment_breadcrumb_and_actions() -> None:
    """``views/detail.html`` builds `[(resource_label, resource_url),
    (current_label, None)]` and renders actions inside the shared
    two-zone toolbar — empty left zone (no search link), and a
    `<menu class="toolbar-right">` carrying the `<li>` commands. Pins
    the "detail actions land at the same right edge as list-page
    actions" rule (no per-view-type toolbar shape)."""
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/detail.html" %}
        {% set resource_url = "/providers" %}
        {% block resource_label %}Providers{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block actions %}<li><a id="edit" href="/providers/1/form">Edit</a></li>{% endblock %}
        {% block content %}body{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html and ">Providers</a>" in html
    assert "Sunrise Therapy" in html
    assert '<div class="toolbar">' in html
    assert '<menu class="toolbar-right">' in html
    # No search link on detail pages — left zone stays empty.
    assert 'class="toolbar-filter-link"' not in html
    assert '<li><a id="edit" href="/providers/1/form">Edit</a></li>' in html


def test_form_new_view_appends_new_segment() -> None:
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_new.html" %}
        {% set resource_url = "/providers" %}
        {% block resource_label %}Providers{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html and ">Providers</a>" in html
    assert ">New</li>" in html or ">New<" in html
    assert '<form id="x"></form>' in html


def test_form_edit_view_renders_three_segment_breadcrumb() -> None:
    env = _make_env()
    _add_child(
        env,
        "stub.html",
        """
        {% extends "views/form_edit.html" %}
        {% set resource_url = "/providers" %}
        {% set resource_detail_url = "/providers/42" %}
        {% block resource_label %}Providers{% endblock %}
        {% block current_label %}Sunrise Therapy{% endblock %}
        {% block content %}<form id="x"></form>{% endblock %}
        """,
    )

    html = env.get_template("stub.html").render(
        request=_request_stub(),
        is_authenticated=False,
        is_development=False,
    )

    assert 'href="/providers"' in html
    assert 'href="/providers/42"' in html
    assert "Sunrise Therapy" in html
    assert ">Edit</li>" in html or ">Edit<" in html


class _RequestStub:
    """Minimal stand-in for the FastAPI ``Request`` that `base.html`
    references via `request.url.path` in the primary-nav section."""

    class _Url:
        path = "/"

    url = _Url()


def _request_stub() -> _RequestStub:
    return _RequestStub()
