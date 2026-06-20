"""`form_rerender` — render a form template with errors / values / banner
injected into the render context, for HTMX in-place re-render on a
validation or business-rule failure.

Generic over the *source* of the error. Today's callers:

  - `mount_create`'s `_render_form_with_errors` (Pydantic 422 on a
    form-encoded create POST — `field_errors` populated, no banner).
  - `auth_pages.post_login` (bad credentials — no per-field error,
    single form-level `banner`).
  - `auth_routes.register_request_handler` (duplicate email /
    invalid password — per-field).

The framework contract is "inject the three context keys
(`form_errors`, `form_values`, `form_banner`) and render the template
as <status_code> + HTML." The macro layer in `_shared/form_fields.html`
does auto-resolution from those keys when the template imports macros
`with context` (see the macros' top-of-file docstring); the banner is
read by `_shared/form_banner.html`'s `form_banner()` macro. Pages
opting in must:

  1. import the form-fields macros `with context`,
  2. drop a `{{ form_banner() }}` call at the top of the form,
  3. set `hx-target="this" hx-swap="outerHTML"` on the `<form>`,
  4. set `hx-target-4xx="this"` so the `response-targets` extension
     (loaded globally in base.html) swaps form-error rerenders that
     come back with a 4xx status. (The swap *style* comes from
     `hx-swap`; the extension overrides only the target, so there is no
     `hx-swap-4xx` — htmx never reads it. See `_shared/form_meta.html`.)

The easiest way to satisfy 1–4 is to wrap the form in the
`_shared/form_meta.html::form_with_errors` macro, which bakes them in.

`status_code` defaults to 422 for the entity-create Pydantic path
and is set per-handler by `form_error_handler` callers. The htmx
default response handler only swaps on 2xx; the `response-targets`
extension reads `hx-target-4xx` (or the more specific
`hx-target-409` / `hx-target-422` / etc) and swaps on 4xx anyway.
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
    status_code: int = 422,
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
      status_code: HTTP status code for the rerender. Default 422
        (generic validation failure). Callers should set a more
        specific code when the failure has one: 409 for "already
        exists" (RFC 9110 §15.5.10), 401 for bad credentials. The
        htmx `response-targets` extension swaps on the matching
        `hx-target-<code>` (or `hx-target-4xx` as the catch-all).

    Returns: <status_code> + HTML Response.
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
        status_code=status_code,
    )
