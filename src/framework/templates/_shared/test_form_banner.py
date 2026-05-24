"""Tests for the `form_banner` macro in `_shared/form_banner.html`.

The macro is the form-level complement to the per-field error rendering
in `form_fields.html`: when an error doesn't pin to a single input
(e.g. fastapi-users `LOGIN_BAD_CREDENTIALS`), the banner sits above
the fields and reads the message from the render context's
`form_banner` key — populated by `src/framework/http/form_rerender.py`.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from selectolax.parser import HTMLParser


def _make_env() -> Environment:
    """Same two-root loader pattern as `test_form_fields.py` — resolves
    `_shared/form_banner.html` from the framework templates root, with
    per-test stubs available via DictLoader."""
    stub = DictLoader({})
    framework = FileSystemLoader(str(Path(__file__).resolve().parents[1]))
    return Environment(loader=ChoiceLoader([stub, framework]))


def _render_with_context(body: str, **context) -> "HTMLParser":
    """Render `body` with `from "_shared/form_banner.html" import
    form_banner with context` prepended. `with context` is required
    for the macro to see the calling render-context vars (e.g.
    `form_banner`) — pinned by a dedicated test below."""
    env = _make_env()
    template = (
        '{%- from "_shared/form_banner.html" import form_banner with context -%}\n'
        f"{body}"
    )
    return HTMLParser(env.from_string(template).render(**context))


def test_form_banner_renders_div_with_role_alert_when_context_set() -> None:
    """With `form_banner` in the render context, the macro emits a
    `<div class="form-banner" role="alert">` carrying the message.
    `role="alert"` makes assistive tech announce it immediately on
    insertion — important for HTMX swap-in-place where the message
    appears without a page reload."""
    tree = _render_with_context(
        "{{ form_banner() }}", form_banner_text="Invalid email or password"
    )
    div = tree.css_first("div.form-banner")
    assert div is not None
    assert div.attributes.get("role") == "alert"
    assert "Invalid email or password" in div.text()


def test_form_banner_no_context_var_renders_nothing() -> None:
    """Default state (form_banner not in context, no explicit
    message=) → the macro emits nothing. Lets templates drop
    `{{ form_banner() }}` unconditionally at the top of every form
    without worrying about producing an empty banner on the happy
    path."""
    tree = _render_with_context("{{ form_banner() }}")
    assert tree.css_first("div.form-banner") is None


def test_form_banner_empty_string_renders_nothing() -> None:
    """An empty `form_banner` is treated as "no banner" — the
    `default(none, true)` filter argument coerces falsy → none, so an
    accidental empty string from upstream doesn't produce an empty
    alert element."""
    tree = _render_with_context("{{ form_banner() }}", form_banner_text="")
    assert tree.css_first("div.form-banner") is None


def test_form_banner_explicit_message_overrides_context() -> None:
    """`form_banner(message="...")` wins over the context var. Same
    override-precedence as the form_fields macros' `error=` param —
    lets a caller synthesize a page-specific banner without
    plumbing through `form_rerender`."""
    tree = _render_with_context(
        '{{ form_banner(message="explicit") }}', form_banner_text="from-ctx"
    )
    div = tree.css_first("div.form-banner")
    assert div is not None
    assert "explicit" in div.text()
    assert "from-ctx" not in div.text()


def test_form_banner_no_with_context_silently_no_op() -> None:
    """Without `with context` on the import, the macro can't see the
    render-context var, so it renders nothing even when `form_banner`
    is set. Sanity check on the "must import with context" requirement
    — same shape as the test in `test_form_fields.py`."""
    env = _make_env()
    template = (
        '{%- from "_shared/form_banner.html" import form_banner -%}'
        "{{ form_banner() }}"
    )
    tree = HTMLParser(
        env.from_string(template).render(form_banner_text="will-not-render")
    )
    assert tree.css_first("div.form-banner") is None
