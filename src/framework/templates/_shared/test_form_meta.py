"""Tests for the ``form_with_errors`` macro in ``_shared/form_meta.html``.

``form_with_errors`` is the wrapper for forms that re-render in place on
a validation failure. It bakes in the four ``response-targets`` attrs
(like ``entity_form(error_swap=True)``) PLUS a ``form_banner()`` slot and
the ``show:window:top`` scroll modifier, so a failed submit surfaces a
form-level summary AND scrolls it into view. These tests pin that
emitted contract; the per-field error rendering lives in
``test_form_fields.py`` and the banner macro in ``test_form_banner.py``.
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


def _render(
    env: Environment,
    args: str,
    body: str = "<p>body</p>",
    **context: object,
) -> str:
    template = (
        '{%- from "_shared/form_meta.html" import form_with_errors with context -%}'
        "{% call form_with_errors(" + args + ") %}" + body + "{% endcall %}"
    )
    return env.from_string(template).render(**context)


def test_form_with_errors_emits_response_targets_quad_and_method() -> None:
    """The four ``hx-target`` / ``hx-swap`` / ``hx-target-4xx`` /
    ``hx-swap-4xx`` attrs all land on the form, and ``method='post'``
    emits ``hx-post``."""
    env = _make_env()
    html = _render(env, "action='/posts', method='post'")
    form = HTMLParser(html).css_first("form")
    assert form.attributes.get("hx-post") == "/posts"
    assert form.attributes.get("hx-target") == "this"
    assert form.attributes.get("hx-target-4xx") == "this"
    assert form.attributes.get("hx-swap-4xx") == "outerHTML"


def test_form_with_errors_swap_scrolls_window_to_top_on_rerender() -> None:
    """The scroll-to-error modifier lives on ``hx-swap`` (NOT
    ``hx-swap-4xx``): the ``response-targets`` extension only overrides
    the *target* on a 4xx, so htmx reads the swap spec — style AND
    modifiers — from the plain ``hx-swap``. A modifier on ``hx-swap-4xx``
    is never read and silently no-ops. ``show:window:top`` scrolls the
    viewport to the top so the re-rendered banner is visible. Pins the
    scroll-to-error behavior against silent regression."""
    env = _make_env()
    html = _render(env, "action='/posts', method='post'")
    form = HTMLParser(html).css_first("form")
    assert form.attributes.get("hx-swap") == "outerHTML show:window:top"


def test_form_with_errors_renders_banner_slot_from_context() -> None:
    """The wrapper drops ``form_banner()`` at the top of the form, which
    reads ``form_banner_text`` from the render context — so a 422
    re-render (which injects that key) shows the summary above the
    fields without the caller wiring anything."""
    env = _make_env()
    html = _render(
        env,
        "action='/posts', method='post'",
        form_banner_text="Please fix the highlighted fields below, then resubmit.",
    )
    banner = HTMLParser(html).css_first("div.form-banner")
    assert banner is not None
    assert banner.attributes.get("role") == "alert"
    assert "Please fix the highlighted fields" in banner.text()


def test_form_with_errors_no_banner_when_context_absent() -> None:
    """No ``form_banner_text`` in context (the fresh-GET case) → the slot
    renders nothing, so the form has no stray empty alert."""
    env = _make_env()
    html = _render(env, "action='/posts', method='post'")
    assert HTMLParser(html).css_first("div.form-banner") is None
