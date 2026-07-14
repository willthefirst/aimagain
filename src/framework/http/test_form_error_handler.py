"""Unit tests for `form_error_handler`.

These cover the decorator's contract in isolation — exception
matching, HX-Request gating, prefill collection, re-raise on miss.
Wire-level behavior (the rerendered HTML body lands at the form
template's `outerHTML` swap target) is pinned at the route layer in
`src/domain/routes/auth/test_auth_routes.py`.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from pydantic import BaseModel

from src.framework.http.form_error_handler import FormError, form_error_handler

pytestmark = pytest.mark.asyncio


class _Body(BaseModel):
    email: str
    password: str


class CustomError(Exception):
    """Caller-defined exception; the decorator is generic over exception type."""

    def __init__(self, reason: str = "boom"):
        self.reason = reason


class OtherError(Exception):
    """Unregistered exception — must re-raise unchanged."""


def _request(htmx: bool = True) -> Request:
    """Build a minimal ASGI Request with the headers we read.

    `form_error_handler` only reads `request.headers.get("HX-Request")`
    — the rest of the ASGI scope is irrelevant. Keep the test request
    minimal so the test doesn't accidentally pin internal Request
    coupling.
    """
    headers = [(b"hx-request", b"true")] if htmx else []
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/x",
            "headers": headers,
        }
    )


async def test_no_exception_passes_through():
    """Happy path: the decorator returns the wrapped function's result
    unchanged. No exception, no rerender, no extra processing."""

    @form_error_handler(
        template="x.html", handlers={CustomError: lambda e: FormError()}
    )
    async def handler(request: Request):
        return {"ok": True}

    result = await handler(request=_request())
    assert result == {"ok": True}


async def test_registered_exception_htmx_returns_rerender(monkeypatch):
    """Matched exception + HX-Request → calls `form_rerender` with the
    handler's FormError. Patch `form_rerender` so the test stays
    framework-isolated — the rendering side is tested in
    `test_form_rerender.py`."""
    captured: dict = {}

    def fake_rerender(**kwargs):
        captured.update(kwargs)
        return "RERENDERED"

    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender", fake_rerender
    )

    @form_error_handler(
        template="auth/_register_form.html",
        prefill_fields=("email",),
        handlers={
            CustomError: lambda e: FormError(
                field_errors={"email": f"failed: {e.reason}"}
            )
        },
    )
    async def handler(request: Request, request_data: _Body):
        raise CustomError("dup")

    result = await handler(
        request=_request(htmx=True),
        request_data=_Body(email="a@b.com", password="pw"),
    )
    assert result == "RERENDERED"
    assert captured["template_name"] == "auth/_register_form.html"
    assert captured["field_errors"] == {"email": "failed: dup"}
    # Email is prefilled from the Pydantic body; password is intentionally
    # never collected by `prefill_fields` so it can't leak back into HTML.
    assert captured["values"] == {"email": "a@b.com"}
    assert "password" not in captured["values"]


async def test_non_htmx_request_reraises(monkeypatch):
    """Same exception, no HX-Request: re-raise so `handle_route_errors`
    can do its JSON-4xx translation. Non-HTMX clients (curl, programmatic,
    contract tests) keep whatever wire shape the route documented."""
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: pytest.fail("should not be called"),
    )

    @form_error_handler(
        template="x.html", handlers={CustomError: lambda e: FormError()}
    )
    async def handler(request: Request):
        raise CustomError()

    with pytest.raises(CustomError):
        await handler(request=_request(htmx=False))


async def test_unregistered_exception_reraises(monkeypatch):
    """Exception that isn't a key (or subclass thereof) of `handlers`
    bubbles up unchanged — even on HX-Request. The decorator is opt-in
    per exception type, not a catch-all."""
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: pytest.fail("should not be called"),
    )

    @form_error_handler(
        template="x.html", handlers={CustomError: lambda e: FormError()}
    )
    async def handler(request: Request):
        raise OtherError("not registered")

    with pytest.raises(OtherError):
        await handler(request=_request(htmx=True))


async def test_exception_subclass_matches_base_handler(monkeypatch):
    """Registering a base class catches subclasses (isinstance check).
    Lets handlers like `{FastAPIUsersException: ...}` act as fallbacks."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    class Specific(CustomError):
        pass

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError(banner="caught")},
    )
    async def handler(request: Request):
        raise Specific()

    result = await handler(request=_request())
    assert result == "ok"
    assert captured["form_banner"] == "caught"


async def test_first_match_wins_for_overlapping_handlers(monkeypatch):
    """When two registered types both match (subclass + base), the one
    listed first wins. Dict-insertion order is the contract — register
    the most specific exception first."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    class Specific(CustomError):
        pass

    @form_error_handler(
        template="x.html",
        handlers={
            Specific: lambda e: FormError(banner="specific"),
            CustomError: lambda e: FormError(banner="base"),
        },
    )
    async def handler(request: Request):
        raise Specific()

    await handler(request=_request())
    assert captured["form_banner"] == "specific"


async def test_two_arg_handler_receives_kwargs(monkeypatch):
    """Handlers can be `(exc) -> FormError` or `(exc, kwargs) -> FormError`.
    Arity is sniffed via `__code__.co_argcount`. The 2-arg form lets a
    handler read other submitted fields for cross-field rules."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    def handler_with_kwargs(exc: Exception, kwargs):
        body = kwargs["request_data"]
        return FormError(field_errors={"email": f"already taken: {body.email}"})

    @form_error_handler(
        template="x.html",
        prefill_fields=("email",),
        handlers={CustomError: handler_with_kwargs},
    )
    async def handler(request: Request, request_data: _Body):
        raise CustomError()

    await handler(request=_request(), request_data=_Body(email="x@y.z", password="pw"))
    assert captured["field_errors"] == {"email": "already taken: x@y.z"}


async def test_prefill_skips_missing_fields(monkeypatch):
    """`prefill_fields` names that aren't present in any kwarg are
    silently omitted — the macro layer falls back to whatever `current=`
    the template passed (typically nothing)."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        prefill_fields=("email", "nonexistent"),
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request, request_data: _Body):
        raise CustomError()

    await handler(request=_request(), request_data=_Body(email="a@b.c", password="p"))
    assert captured["values"] == {"email": "a@b.c"}


async def test_handler_with_dict_kwarg_prefill(monkeypatch):
    """When the body lands as a plain dict (e.g. parsed form data),
    prefill reads keys. Pydantic models, dicts, and bare kwargs are
    the three accepted shapes — see `_collect_prefill`."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        prefill_fields=("email",),
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request, payload: dict):
        raise CustomError()

    await handler(request=_request(), payload={"email": "from-dict@x.io"})
    assert captured["values"] == {"email": "from-dict@x.io"}


async def test_prefill_reads_plain_attribute_object(monkeypatch):
    """Some FastAPI deps aren't Pydantic — `OAuth2PasswordRequestForm`
    is a plain class with `.username` / `.password` set in `__init__`.
    The prefill helper falls back to `getattr` for plain objects
    (guarded against callables so `Request.headers` doesn't spuriously
    match). Pinned here so a future refactor of `_lookup_field` can't
    silently regress the login prefill path."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    class OAuthLike:
        def __init__(self, username: str, password: str):
            self.username = username
            self.password = password

    @form_error_handler(
        template="x.html",
        prefill_fields=("username",),
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request, credentials: OAuthLike):
        raise CustomError()

    await handler(request=_request(), credentials=OAuthLike("u@x.io", "secret"))
    assert captured["values"] == {"username": "u@x.io"}


async def test_require_htmx_false_rerenders_for_non_htmx_calls(monkeypatch):
    """Browser-only routes (no JSON contract for programmatic clients)
    pass `require_htmx=False`. A registered exception then renders the
    form fragment regardless of the `HX-Request` header. The login
    wrapper is the canonical case — programmatic clients use
    `/auth/jwt/login` instead, so the wrapper has no JSON contract to
    preserve."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError(banner="b")},
        require_htmx=False,
    )
    async def handler(request: Request):
        raise CustomError()

    result = await handler(request=_request(htmx=False))
    assert result == "ok"
    assert captured["form_banner"] == "b"


async def test_auto_prefill_collects_all_non_sensitive_pydantic_fields(monkeypatch):
    """`prefill_fields=None` (the post-PR-#7 default) auto-detects
    from the submitted Pydantic body. Every non-sensitive declared
    field is prefilled; password-like fields are dropped by the
    denylist."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    class _Body(BaseModel):
        email: str
        display_name: str
        password: str
        token: str
        new_password: str

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError()},
        # `prefill_fields` omitted — auto-detect path.
    )
    async def handler(request: Request, request_data: _Body):
        raise CustomError()

    await handler(
        request=_request(),
        request_data=_Body(
            email="u@x.io",
            display_name="Pat",
            password="secret",
            token="ABC",
            new_password="also-secret",
        ),
    )
    # Visible fields land; sensitive ones are dropped.
    assert captured["values"] == {
        "email": "u@x.io",
        "display_name": "Pat",
    }
    assert "password" not in captured["values"]
    assert "new_password" not in captured["values"]
    assert "token" not in captured["values"]


async def test_explicit_prefill_still_drops_sensitive_fields(monkeypatch):
    """Defense in depth: a route that explicitly passes
    `prefill_fields=("password",)` still gets the password dropped.
    The denylist applies to both modes — there is no path that
    lets a password round-trip into HTML."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        prefill_fields=("email", "password"),  # password in the allowlist
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request, request_data: _Body):
        raise CustomError()

    await handler(
        request=_request(),
        request_data=_Body(email="u@x.io", password="secret"),
    )
    assert captured["values"] == {"email": "u@x.io"}
    assert "password" not in captured["values"]


async def test_auto_prefill_handles_plain_attribute_objects(monkeypatch):
    """OAuth2PasswordRequestForm-style classes (plain Python objects
    with attributes set in `__init__`) are discovered via `__dict__`.
    `username` lands; `password` is dropped."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    class OAuthLike:
        def __init__(self, username: str, password: str, scope: str = ""):
            self.username = username
            self.password = password
            self.scope = scope

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request, credentials: OAuthLike):
        raise CustomError()

    await handler(
        request=_request(),
        credentials=OAuthLike("u@x.io", "secret", scope="read"),
    )
    assert captured["values"] == {"username": "u@x.io", "scope": "read"}
    assert "password" not in captured["values"]


async def test_auto_prefill_returns_empty_when_no_form_data_in_kwargs(monkeypatch):
    """A route with no body — just framework deps — auto-detects
    nothing and the rerender lands with empty `values`. The macros
    fall back to whatever `current=` the template passed (typically
    nothing)."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError()},
    )
    async def handler(request: Request):
        raise CustomError()

    await handler(request=_request())
    assert captured["values"] == {}


async def test_catches_resolves_through_registry(monkeypatch):
    """`catches=(ExceptionType,)` pulls (status_code, field, message)
    from `FormErrorRegistry`. Equivalent to writing a `handlers=`
    entry by hand, but doesn't require a route-level lambda."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    from src.framework.http.form_error_registry import (
        _clear_for_testing,
        register_form_error,
    )

    class _CatchMe(Exception):
        pass

    register_form_error(
        _CatchMe, status_code=409, field="email", message="dup via registry"
    )
    try:

        @form_error_handler(
            template="x.html",
            catches=(_CatchMe,),
        )
        async def handler(request: Request):
            raise _CatchMe()

        result = await handler(request=_request())
        assert result == "ok"
        assert captured["field_errors"] == {"email": "dup via registry"}
        assert captured["status_code"] == 409
    finally:
        _clear_for_testing()


async def test_explicit_handler_wins_over_catches(monkeypatch):
    """When both `handlers=` and `catches=` would match the same
    exception, the explicit handler wins. Lets a route opt into the
    registry generally and override copy for one error type."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    from src.framework.http.form_error_registry import (
        _clear_for_testing,
        register_form_error,
    )

    class _CatchMe(Exception):
        pass

    register_form_error(_CatchMe, status_code=409, field="email", message="registry")
    try:

        @form_error_handler(
            template="x.html",
            catches=(_CatchMe,),
            handlers={
                _CatchMe: lambda e: FormError(
                    field_errors={"email": "route override"},
                    status_code=400,
                ),
            },
        )
        async def handler(request: Request):
            raise _CatchMe()

        await handler(request=_request())
        assert captured["field_errors"] == {"email": "route override"}
        assert captured["status_code"] == 400
    finally:
        _clear_for_testing()


async def test_catches_unregistered_exception_raises_config_error():
    """Listing an exception under `catches=` that isn't registered
    in `FormErrorRegistry` is a config bug — fail loudly so the gap
    is obvious. Alternative is silently re-raising, which would look
    like "the decorator isn't catching my exception" and waste
    diagnosis time."""

    class _NotRegistered(Exception):
        pass

    @form_error_handler(template="x.html", catches=(_NotRegistered,))
    async def handler(request: Request):
        raise _NotRegistered()

    with pytest.raises(RuntimeError, match="not registered"):
        await handler(request=_request())


async def test_context_builder_threads_through(monkeypatch):
    """`context_builder` receives the route's kwargs and returns a dict
    that becomes the rerender's render context. Used for things like
    `next_url` that the form template needs but the exception doesn't
    carry."""
    captured: dict = {}
    monkeypatch.setattr(
        "src.framework.http.form_error_handler.form_rerender",
        lambda **kw: captured.update(kw) or "ok",
    )

    @form_error_handler(
        template="x.html",
        handlers={CustomError: lambda e: FormError()},
        context_builder=lambda kwargs: {"next_url": "/elsewhere"},
    )
    async def handler(request: Request):
        raise CustomError()

    await handler(request=_request())
    assert captured["context"] == {"next_url": "/elsewhere"}
