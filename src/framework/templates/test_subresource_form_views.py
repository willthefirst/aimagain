"""Tests for the spec-driven sub-resource form view templates.

`views/subresource_form_new.html` and `views/subresource_form_edit.html`
let an owned-subentity spec declare `templates.form_partial =
"<entity>/_form_<entity>.html"` and skip the per-entity wrapper file —
the view template extends the regular form view chrome and renders the
partial inside `form_content`. These tests pin two contracts:

1. The view templates correctly inherit the create/edit chrome
   (breadcrumb, H1, container wrapper).
2. Rendering `views/subresource_form_{new,edit}.html` directly with a
   `form_partial` in context renders that partial's body inside the
   `<div class="entity-form-page">` form wrapper.
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
        path = "/clinicians/42/licensures/form"

    url = _Url()
    query_params: dict[str, str] = {}


def test_subresource_form_new_includes_partial_body() -> None:
    """Rendering `views/subresource_form_new.html` with
    `form_partial="stub_partial.html"` in context includes the partial's
    body inside the chrome's form-page wrapper. Passes
    `_breadcrumb_items` because parent-owned specs (the real callers)
    always have it injected — that's the production code path."""
    env = _make_env()
    _add_child(env, "stub_partial.html", '<form id="partial-form">partial body</form>')

    html = env.get_template("views/subresource_form_new.html").render(
        request=_RequestStub(),
        is_authenticated=False,
        is_development=False,
        entity_name="clinician_licensure",
        create_heading="Create licensure",
        form_partial="stub_partial.html",
        _breadcrumb_items=[
            ("Clinicians", "/clinicians", None),
            ("Sunrise", "/clinicians/42", None),
            ("Licensures", None, None),
        ],
    )

    tree = HTMLParser(html)
    assert '<form id="partial-form">partial body</form>' in html
    # H1 still reads from `create_heading` — chrome inherited from form_new.
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None and h1.text(strip=True) == "Create licensure"
    # Form content lives inside `entity-form-page` wrapper.
    wrapper = tree.css_first("div.entity-form-page")
    assert wrapper is not None
    assert "partial body" in wrapper.html


def test_subresource_form_edit_includes_partial_body() -> None:
    """Edit-side companion — `views/subresource_form_edit.html` includes
    the partial inside the same form-page wrapper, with `edit_heading`
    as the H1."""
    env = _make_env()
    _add_child(env, "stub_partial.html", '<form id="partial-form">edit body</form>')

    html = env.get_template("views/subresource_form_edit.html").render(
        request=_RequestStub(),
        is_authenticated=False,
        is_development=False,
        entity_name="clinician_licensure",
        edit_heading="Edit licensure",
        resource_detail_url="/clinicians/42/licensures/7",
        form_partial="stub_partial.html",
        _breadcrumb_items=[
            ("Clinicians", "/clinicians", None),
            ("Sunrise", "/clinicians/42", None),
            ("Licensures", "/clinicians/42/licensures", None),
            ("License XYZ", None, None),
        ],
    )

    tree = HTMLParser(html)
    assert '<form id="partial-form">edit body</form>' in html
    h1 = tree.css_first("div.toolbar h1")
    assert h1 is not None and h1.text(strip=True) == "Edit licensure"
    wrapper = tree.css_first("div.entity-form-page")
    assert wrapper is not None


def test_subresource_form_new_inherits_form_new_view_type_for_contract() -> None:
    """The view-type contract validator walks `{% extends %}` one hop to
    find required keys. `views/subresource_form_new.html` extends
    `views/form_new.html`, so a render that omits `create_heading` /
    `entity_name` surfaces the same `ViewTypeContextError` it would for
    a direct `views/form_new.html` render."""
    from src.framework.rendering.view_type_contract import (
        missing_required_keys,
        view_type_for,
    )

    assert view_type_for("views/subresource_form_new.html") == "views/form_new.html"
    assert view_type_for("views/subresource_form_edit.html") == "views/form_edit.html"
    # Sanity: a context missing `create_heading` is flagged.
    missing = missing_required_keys(
        "views/subresource_form_new.html",
        {"entity_name": "x"},
    )
    assert "create_heading" in missing
