"""Tests for the ``entity_form`` macro in ``_shared/forms.html``.

``entity_form`` is the canonical ``<form hx-{method}="{url}">`` wrapper
that every top-level entity create/edit form composes (per #1193's
component-library rule). Sub-resource add forms on the clinician
credential list pages use the same macro — wrapped in
``<section class="entity-form-page">`` so the entity-form subgrid
alignment applies the same way it does on the chrome-supplied wrapper.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    stub = DictLoader({})
    framework = FileSystemLoader(
        str(Path(__file__).resolve().parents[1])
    )  # src/framework/templates
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render(env: Environment, args: str, body: str = "<p>body</p>") -> str:
    template = (
        '{%- from "_shared/forms.html" import entity_form -%}'
        "{% call entity_form(" + args + ") %}" + body + "{% endcall %}"
    )
    return env.from_string(template).render()


def test_entity_form_defaults_to_patch_and_emits_caller_body() -> None:
    """The default method is ``patch`` — matches the dominant edit-form
    case (org / clinician / program). The caller body renders inside
    the ``<form>``."""
    env = _make_env()
    html = _render(env, "'/organizations/abc'")
    tree = HTMLParser(html)
    form = tree.css_first("form")
    assert form is not None
    assert form.attributes.get("hx-patch") == "/organizations/abc"
    assert form.css_first("p").text() == "body"


def test_entity_form_method_post_emits_hx_post() -> None:
    """Create forms pass ``method='post'`` so the wrapper emits
    ``hx-post=...`` instead of ``hx-patch=...``."""
    env = _make_env()
    html = _render(env, "'/posts', method='post'")
    tree = HTMLParser(html)
    form = tree.css_first("form")
    assert form.attributes.get("hx-post") == "/posts"
    assert "hx-patch" not in form.attributes


def test_entity_form_no_error_swap_attrs_by_default() -> None:
    """Default is no error-swap; the response-targets extension stays
    inactive unless the caller opts in."""
    env = _make_env()
    html = _render(env, "'/organizations/abc'")
    tree = HTMLParser(html)
    form = tree.css_first("form")
    for attr in ("hx-target", "hx-swap", "hx-target-4xx", "hx-swap-4xx"):
        assert attr not in form.attributes, f"Expected no {attr}"


def test_entity_form_error_swap_emits_response_targets_quad() -> None:
    """With ``error_swap=True`` the four ``hx-target`` / ``hx-swap`` /
    ``hx-target-4xx`` / ``hx-swap-4xx`` attrs all land on the form.
    The 4xx pair is what activates the response-targets extension so a
    422 validation re-render swaps in place."""
    env = _make_env()
    html = _render(env, "'/posts', method='post', error_swap=True")
    tree = HTMLParser(html)
    form = tree.css_first("form")
    assert form.attributes.get("hx-target") == "this"
    assert form.attributes.get("hx-swap") == "outerHTML"
    assert form.attributes.get("hx-target-4xx") == "this"
    assert form.attributes.get("hx-swap-4xx") == "outerHTML"
