"""Unit tests for `form_rerender` — focus on the three context keys
this helper is responsible for (`form_errors`, `form_values`,
`form_banner`) and their default shapes.

The downstream macro auto-resolution + banner rendering have their own
tests under `src/framework/templates/_shared/`; this file owns the
*framework contract*: regardless of error source, the same three keys
land in the rendered context with the documented defaults.

The renderer (`APIResponse.html_response`) is monkeypatched so the
tests run without templating — the assertion target is "what did
`form_rerender` ask the renderer to put in the context", not "what
HTML came out".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Response

from src.framework.http.form_rerender import form_rerender


def _stub_renderer():
    """Capture-and-return stub for `APIResponse.html_response`. The
    returned function records its call kwargs onto `.calls` so the
    test can assert on the template_name + context that landed."""
    calls: list[dict] = []

    def stub(template_name, context, request, *, current_user=None):
        calls.append(
            {
                "template_name": template_name,
                "context": context,
                "current_user": current_user,
            }
        )
        return Response(content="ok", media_type="text/html", status_code=200)

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


def test_form_rerender_injects_three_keys_with_documented_defaults():
    """Bare call (no field_errors / form_banner / values) still lands
    `form_errors={}`, `form_values={}`, `form_banner_text=None` in the
    context. Pins the "always present, always shape-stable" half of
    the contract so templates can read the keys unconditionally."""
    renderer = _stub_renderer()
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        form_rerender(
            request=SimpleNamespace(),
            template_name="auth/login.html",
            context={"next_url": "/home"},
        )
    ctx = renderer.calls[0]["context"]
    assert ctx["form_errors"] == {}
    assert ctx["form_values"] == {}
    assert ctx["form_banner_text"] is None
    # Caller-supplied keys survive intact.
    assert ctx["next_url"] == "/home"


def test_form_rerender_threads_field_errors_and_values():
    """`field_errors` and `values` land verbatim under their
    framework-canonical names so the macros' auto-resolution finds
    them without per-page wiring."""
    renderer = _stub_renderer()
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        form_rerender(
            request=SimpleNamespace(),
            template_name="x.html",
            context={},
            field_errors={"email": "Required"},
            values={"email": "u@example.com", "password": "kept"},
        )
    ctx = renderer.calls[0]["context"]
    assert ctx["form_errors"] == {"email": "Required"}
    assert ctx["form_values"] == {"email": "u@example.com", "password": "kept"}


def test_form_rerender_form_banner_lands_as_form_banner_text_context_key():
    """The `form_banner=` kwarg lands under context key
    `form_banner_text` (not `form_banner`) so it doesn't shadow the
    `form_banner` macro inside the template — see the docstring in
    `_shared/form_banner.html` for the gotcha. Used by auth/login for
    "Invalid email or password" where the error doesn't pin to one
    field."""
    renderer = _stub_renderer()
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        form_rerender(
            request=SimpleNamespace(),
            template_name="x.html",
            context={},
            form_banner="Invalid email or password",
        )
    assert (
        renderer.calls[0]["context"]["form_banner_text"] == "Invalid email or password"
    )


def test_form_rerender_caller_context_cannot_override_framework_keys():
    """If a caller's `context` already contains `form_errors` (etc.),
    the helper's framework keys win. Defends against accidental
    leakage where a page's GET handler stuffed something into
    `form_errors` and the rerender path silently inherited it."""
    renderer = _stub_renderer()
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        form_rerender(
            request=SimpleNamespace(),
            template_name="x.html",
            context={
                "form_errors": {"stale": "value"},
                "form_banner_text": "stale",
            },
            field_errors={"fresh": "msg"},
            form_banner="fresh banner",
        )
    ctx = renderer.calls[0]["context"]
    assert ctx["form_errors"] == {"fresh": "msg"}
    assert ctx["form_banner_text"] == "fresh banner"


def test_form_rerender_returns_200_html_response():
    """Status code is 200 (not 4xx) because HTMX's default
    response-handling table only swaps on 2xx. The non-HTMX / JSON
    contract is the caller's responsibility — `form_rerender` is the
    HTMX-side branch."""
    renderer = _stub_renderer()
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        resp = form_rerender(
            request=SimpleNamespace(), template_name="x.html", context={}
        )
    assert resp.status_code == 200
    assert resp.media_type == "text/html"


def test_form_rerender_passes_current_user_through_to_renderer():
    """`current_user` is forwarded to `APIResponse.html_response` so
    the chrome layer renders identity widgets correctly on the
    re-render (logged-in pages re-render with the same chrome they
    had on the GET)."""
    renderer = _stub_renderer()
    user = SimpleNamespace(id="u-1")
    with patch(
        "src.framework.http.form_rerender.APIResponse.html_response", new=renderer
    ):
        form_rerender(
            request=SimpleNamespace(),
            template_name="x.html",
            context={},
            current_user=user,
        )
    assert renderer.calls[0]["current_user"] is user
