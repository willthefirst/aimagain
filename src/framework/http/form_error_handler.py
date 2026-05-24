"""`form_error_handler` — route decorator that turns registered
exceptions into a form rerender on `HX-Request: true`.

Before this helper, each route that wanted inline form error UX had
to wrap its body in a hand-rolled try/except → `form_rerender` block
(see git history of `register_request_handler` and
`auth_pages.post_login`). The boilerplate grew once per route, plus a
guard on `HX-Request` per branch, plus the manual list of fields to
prefill. This decorator collapses that to a declaration on the route:

    @form_error_handler(
        template="auth/_register_form.html",
        prefill_fields=("email",),
        handlers={
            UserAlreadyExists: lambda e: FormError(
                field_errors={"email": "An account with this email already exists."}
            ),
            InvalidPasswordException: lambda e: FormError(
                field_errors={"password": e.reason}
            ),
        },
    )
    async def register_request_handler(...):
        ...

What it does on call:

  1. Run the wrapped route function.
  2. If it raises an exception that's an instance of any key in
     `handlers`, AND the request carries `HX-Request: true`, look up
     the matching handler, build a `FormError`, and return a 200 + the
     form fragment via `form_rerender`. Prefill values are pulled
     from the route's kwargs by `prefill_fields` name (typically a
     Pydantic body model with attribute access).
  3. If the exception isn't registered, OR the request isn't HTMX,
     re-raise so the outer `handle_route_errors` decorator does its
     usual JSON-4xx translation. Non-HTMX clients (programmatic, curl,
     contract tests) keep whatever wire shape the route documented.

Exception subclasses match by isinstance, so a base class in
`handlers` catches all subclasses. First-match wins (dict-insertion
order) — register the most specific exception first.

Status code is 200 (not 4xx) because HTMX's default response handler
only swaps on 2xx — same trade-off `form_rerender` already makes and
already explains. The follow-up PR adopts htmx's response-targets
extension so a 4xx response can still drive the swap; this decorator
will gain a `status_code=` per handler at that point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Mapping, Sequence

from fastapi import Request

from src.framework.http.form_rerender import form_rerender


@dataclass(frozen=True)
class FormError:
    """The shape a `handlers[<Exception>]` callable returns.

    Either or both of `field_errors` (per-field inline messages) and
    `banner` (form-level alert) can be set; the form template renders
    whichever are present (per-field via `form_fields.html` macro
    auto-resolution, banner via `_shared/form_banner.html`'s
    `form_banner()` macro). Both empty is a no-op rerender — usually
    a sign the handler should have re-raised instead.
    """

    field_errors: Mapping[str, str] = field(default_factory=dict)
    banner: str | None = None


# A handler is a pure function from the exception (and the route's
# kwargs, for cases that need the body) to a FormError. Keeping it
# pure means the registry can be inspected statically by future lint
# (PR #4) without invoking framework machinery.
FormErrorHandler = Callable[[Exception], FormError]
FormErrorHandlerWithKwargs = Callable[[Exception, Mapping[str, Any]], FormError]


def form_error_handler(
    *,
    template: str,
    handlers: Mapping[type[Exception], FormErrorHandler | FormErrorHandlerWithKwargs],
    prefill_fields: Sequence[str] = (),
    context_builder: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    require_htmx: bool = True,
):
    """Decorator factory. See module docstring.

    Args:
      template: form fragment template to re-render on a matched
        exception. Typically the same fragment the GET page includes
        — `<dir>/_<name>_form.html` by the auth-routes convention,
        `<dir>/_<name>_fragment.html` by the entity-route convention.
      handlers: `{ExceptionType: (e -> FormError) | (e, kwargs -> FormError)}`.
        A two-arg callable receives the route's kwargs dict so it can
        read other submitted fields (e.g. for cross-field rules); the
        single-arg form is enough when the exception itself carries
        the error message.
      prefill_fields: names of fields to copy into `form_values` so the
        rerender keeps what the user typed. Reads from the route's
        kwargs: if a value is a Pydantic model the attribute is
        looked up; if it's a dict, the key is looked up; otherwise
        the kwarg with that name is used directly. Password-like
        fields should be omitted — never echo a password.
      context_builder: optional callable from route kwargs to extra
        render context (e.g. `next_url` for the login form). Same shape
        as the existing `context=` param on `form_rerender`.
      require_htmx: gate the rerender on `HX-Request: true`. Default
        True (the register / programmatic-client split: HTMX gets HTML,
        programmatic clients keep their JSON-4xx contract). Set False
        for routes that are *only* a browser form — there is no JSON
        contract to preserve, so the rerender should fire on every
        client (login wrapper `/auth/login`; programmatic auth clients
        use `/auth/jwt/login` instead). Re-raise to `handle_route_errors`
        still happens when `handlers` doesn't match — the gate is just
        about whether HTMX is required *for matched* exceptions.
    """

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                handler = _match_handler(handlers, exc)
                if handler is None:
                    raise
                request = _extract_request(kwargs)
                if request is None:
                    raise
                if require_htmx and request.headers.get("HX-Request") != "true":
                    # Non-HTMX caller on a route that preserves a JSON
                    # contract (e.g. `/auth/register` for programmatic
                    # clients) — preserve the original error so
                    # `handle_route_errors` turns it into the documented
                    # JSON 4xx. Browser-only routes pass `require_htmx=False`
                    # and fall through to the rerender path on every
                    # client.
                    raise
                form_error = _call_handler(handler, exc, kwargs)
                values = _collect_prefill(kwargs, prefill_fields)
                context = context_builder(kwargs) if context_builder else None
                return form_rerender(
                    request=request,
                    template_name=template,
                    context=context,
                    field_errors=dict(form_error.field_errors),
                    form_banner=form_error.banner,
                    values=values,
                )

        return wrapper

    return decorator


def _match_handler(
    handlers: Mapping[type[Exception], Any], exc: Exception
) -> Any | None:
    """Return the first handler whose key type matches `exc` (isinstance).

    Dict-insertion order is preserved on Python 3.7+, so callers can
    put a subclass before its base to disambiguate (e.g. a custom
    `DuplicateEmailWithReason` ahead of `UserAlreadyExists`).
    """
    for exc_type, handler in handlers.items():
        if isinstance(exc, exc_type):
            return handler
    return None


def _call_handler(handler: Any, exc: Exception, kwargs: Mapping[str, Any]) -> FormError:
    """Invoke a 1-arg or 2-arg handler uniformly.

    Single-arg signature is the common case (the exception carries
    the message); 2-arg is the escape hatch for handlers that need to
    inspect submitted fields. We sniff arity via `__code__.co_argcount`
    rather than wrapping every handler — keeps the call site readable
    in registry literals.
    """
    co = getattr(handler, "__code__", None)
    if co is not None and co.co_argcount >= 2:
        return handler(exc, kwargs)
    return handler(exc)


def _extract_request(kwargs: Mapping[str, Any]) -> Request | None:
    """Pull the `Request` out of the route's resolved kwargs.

    FastAPI resolves parameters by name; routes that opt into this
    decorator declare `request: Request` so the framework injects it.
    We look it up by name first (cheap), then fall back to a type
    scan (handles routes that name the param differently).
    """
    req = kwargs.get("request")
    if isinstance(req, Request):
        return req
    for v in kwargs.values():
        if isinstance(v, Request):
            return v
    return None


def _collect_prefill(
    kwargs: Mapping[str, Any], fields: Sequence[str]
) -> dict[str, Any]:
    """Build the `{name: value}` dict the rerender uses for prefill.

    Search order per field:
      1. Any kwarg whose value is a Pydantic model (or any object
         exposing the field as an attribute).
      2. Any kwarg whose value is a dict containing the field.
      3. The kwarg with the exact name.

    First non-None hit wins. Missing fields are silently omitted so the
    rerender macro falls back to whatever explicit `current=` the
    template passed (typically also nothing).
    """
    out: dict[str, Any] = {}
    for name in fields:
        for v in kwargs.values():
            value = _lookup_field(v, name)
            if value is not None:
                out[name] = value
                break
        else:
            if name in kwargs and kwargs[name] is not None:
                out[name] = kwargs[name]
    return out


def _lookup_field(container: Any, name: str) -> Any:
    """Pull `name` from `container` if it carries the field.

    Returns None on miss (caller iterates). Three accepted shapes:

      1. **dict** — `container.get(name)` (typical for raw form payloads
         that haven't been adapted into a model yet).
      2. **Pydantic model** — `getattr(container, name, None)`. Detected
         by `model_dump` (v2) or `__fields__` (v1/v2 both expose it).
      3. **Plain object with the attribute** — used by FastAPI deps that
         aren't Pydantic, e.g. `OAuth2PasswordRequestForm` (the login
         credentials object has `.username` / `.password` set in
         `__init__`). The callable-guard excludes methods, so `Request`
         (`.headers`, `.method`, etc.) won't spuriously match unless
         the caller actually asks for `prefill_fields=("headers",)`,
         which is caller error.

    The framework-injected objects (Request, repos, managers) generally
    don't have form-field attributes, so they return None and the
    caller's loop moves on.
    """
    if isinstance(container, dict):
        return container.get(name)
    if hasattr(container, "model_dump") or hasattr(container, "__fields__"):
        # Pydantic v1/v2 model — read as an attribute.
        return getattr(container, name, None)
    value = getattr(container, name, None)
    if callable(value):
        return None
    return value
