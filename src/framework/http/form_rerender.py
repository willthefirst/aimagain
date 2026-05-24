"""`form_rerender` — render a form template with errors / values / banner
injected into the render context, for HTMX in-place re-render on a
validation or business-rule failure.

Generic over the *source* of the error. Today's callers:

  - `mount_create`'s `_render_form_with_errors` (Pydantic 422 on a
    form-encoded create POST — `field_errors` populated, no banner).
  - `auth_pages.post_login` (fastapi-users `LOGIN_BAD_CREDENTIALS` — no
    per-field error, single form-level `banner`).

The framework contract is "inject the three context keys
(`form_errors`, `form_values`, `form_banner`) and render the template
as 200 + HTML." The macro layer in `_shared/form_fields.html` does
auto-resolution from those keys when the template imports macros
`with context` (see the macros' top-of-file docstring); the banner is
read by `_shared/form_banner.html`'s `form_banner()` macro. Pages
opting in must:

  1. import the form-fields macros `with context`,
  2. drop a `{{ form_banner() }}` call at the top of the form,
  3. set `hx-target="this" hx-swap="outerHTML"` on the `<form>`.

Status code is 200 (not 4xx) because HTMX's default response-handling
table only swaps on 2xx. Branches that hit this helper are gated on
`HX-Request: true` at the call site — non-HTMX clients keep whatever
JSON / 4xx contract the route documented.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response

from src.framework.http.responses import APIResponse


def form_rerender(
    *,
    request: Request,
    template_name: str,
    context: dict | None = None,
    field_errors: dict[str, str] | None = None,
    form_banner: str | None = None,
    values: dict | None = None,
    current_user: Any = None,
) -> Response:
    """Render `template_name` with form-error context injected.

    Args:
      request: incoming Request (FastAPI templates need it).
      template_name: the form template to re-render (typically the same
        template the GET page used — `auth/login.html`, the form_new
        page for a mounted entity, etc.).
      context: caller-built render context (chrome / page-specific
        vars). The three form-error keys below are merged in *after*
        so the helper's contract wins on key conflict.
      field_errors: per-field `{name: message}`. Macros auto-resolve
        via `form_errors.get(name)` when the form template imports
        them `with context`.
      form_banner: single form-level error message (e.g. "Invalid
        email or password"). Rendered by `_shared/form_banner.html`'s
        `form_banner()` macro at the top of the form. Use when the
        error doesn't pin to a single input.
      values: raw submitted payload, used for prefill so the user
        doesn't lose what they typed. `_shared/form_fields.html`
        macros auto-resolve via `form_values.get(name, current)`.
      current_user: the authenticated user (or None) so the chrome
        layer can render identity widgets correctly.

    Returns: 200 + HTML Response.
    """
    merged: dict = {**(context or {})}
    merged["form_errors"] = field_errors or {}
    merged["form_values"] = values or {}
    # Context key is `form_banner_text` (not `form_banner`) so it
    # doesn't shadow the `form_banner` macro inside the template — see
    # the docstring in `_shared/form_banner.html` for the gotcha.
    merged["form_banner_text"] = form_banner
    return APIResponse.html_response(
        template_name=template_name,
        context=merged,
        request=request,
        current_user=current_user,
    )
