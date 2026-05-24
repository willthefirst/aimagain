"""Unit tests for `FormErrorRegistry` — the exception-type ⇒ rendering-
rules lookup that `@form_error_handler(catches=...)` resolves through.

Covers the registration contract (XOR-fields), the isinstance lookup
shape, and the `render_with_registry` adapter that converts a
registered mapping into a `FormError`. Integration with the decorator
is covered by `test_form_error_handler.py`; the contract pin against
real routes lives in `test_form_error_handler_contracts.py`.
"""

from __future__ import annotations

import pytest

from src.framework.http.form_error_handler import FormError
from src.framework.http.form_error_registry import (
    _clear_for_testing,
    lookup_form_error,
    register_form_error,
    render_with_registry,
)


class _StubError(Exception):
    """Synthetic exception used by every test in this file. Registered
    fresh per test via `_clear_for_testing` so the registry state never
    leaks between cases."""

    def __init__(self, reason: str = "default reason"):
        self.reason = reason


@pytest.fixture(autouse=True)
def _reset_registry():
    """Snapshot-restore the registry around each test. The
    framework-boot fastapi-users registrations are reinstalled by
    `_clear_for_testing` so the rest of the suite (which depends on
    them) keeps working."""
    yield
    _clear_for_testing()


def test_register_then_lookup_returns_the_mapping():
    register_form_error(_StubError, status_code=409, field="x", message="literal")
    mapping = lookup_form_error(_StubError())
    assert mapping is not None
    assert mapping.status_code == 409
    assert mapping.field == "x"
    assert mapping.message == "literal"
    assert mapping.banner is False


def test_lookup_returns_none_for_unregistered_exception():
    """Unregistered exception types don't match — the decorator falls
    through and re-raises so `handle_route_errors` does its usual
    JSON-4xx translation."""

    class _Unregistered(Exception):
        pass

    assert lookup_form_error(_Unregistered()) is None


def test_subclass_matches_base_registration():
    """isinstance lookup means a subclass picks up its base class's
    registration. Lets framework code register `FastAPIUsersException`
    once and have every subclass inherit."""

    class _Specific(_StubError):
        pass

    register_form_error(_StubError, status_code=422, field="x", message="base")
    mapping = lookup_form_error(_Specific())
    assert mapping is not None
    assert mapping.message == "base"


def test_render_with_registry_builds_field_form_error():
    register_form_error(_StubError, status_code=409, field="email", message="dup")
    fe = render_with_registry(_StubError())
    assert isinstance(fe, FormError)
    assert fe.field_errors == {"email": "dup"}
    assert fe.banner is None
    assert fe.status_code == 409


def test_render_with_registry_builds_banner_form_error():
    register_form_error(_StubError, status_code=401, banner=True, message="bad creds")
    fe = render_with_registry(_StubError())
    assert isinstance(fe, FormError)
    assert fe.field_errors == {}
    assert fe.banner == "bad creds"
    assert fe.status_code == 401


def test_render_with_registry_calls_message_from_with_exception():
    """`message_from` lets the registered mapping pull the user-visible
    message off the exception instance — used for exceptions that
    carry their own policy detail (`InvalidPasswordException.reason`,
    Pydantic ValidationError's per-field details)."""
    register_form_error(
        _StubError,
        status_code=422,
        field="password",
        message_from=lambda e: f"policy: {e.reason}",
    )
    fe = render_with_registry(_StubError(reason="too short"))
    assert fe is not None
    assert fe.field_errors == {"password": "policy: too short"}


def test_render_with_registry_returns_none_for_unregistered():
    """Mirrors `lookup_form_error` — unregistered exception → None.
    The decorator's `catches=` resolution treats this as a config bug
    (listed in catches but not registered) and raises a RuntimeError
    with a useful diagnostic; pinned at the integration layer."""

    class _Unregistered(Exception):
        pass

    assert render_with_registry(_Unregistered()) is None


def test_register_rejects_field_and_banner_together():
    """`field=` and `banner=True` are mutually exclusive. The
    registration call fails loudly at import time rather than emitting
    a malformed mapping that would render strangely (a banner that
    also tries to point at a field)."""
    with pytest.raises(ValueError, match="exactly one of"):
        register_form_error(
            _StubError,
            status_code=409,
            field="email",
            banner=True,
            message="x",
        )


def test_register_rejects_neither_field_nor_banner():
    """A registration with neither `field=` nor `banner=True` is a
    no-op (the render path has nothing to do). Fail at registration
    so the missing field is obvious."""
    with pytest.raises(ValueError, match="exactly one of"):
        register_form_error(_StubError, status_code=409, message="x")


def test_register_rejects_message_and_message_from_together():
    """Same xor for the message source: literal or callable, not both."""
    with pytest.raises(ValueError, match="exactly one of"):
        register_form_error(
            _StubError,
            status_code=409,
            field="x",
            message="literal",
            message_from=lambda e: "dynamic",
        )


def test_register_rejects_neither_message_nor_message_from():
    """A mapping without any message source can't render. Fail at
    registration so the gap is obvious."""
    with pytest.raises(ValueError, match="exactly one of"):
        register_form_error(_StubError, status_code=409, field="x")


def test_first_registration_wins_for_overlapping_types():
    """When a subclass and its base are both registered, the *first*
    one listed wins by isinstance scan order (dict-insertion order).
    Register the most specific exception first to disambiguate."""

    class _Specific(_StubError):
        pass

    register_form_error(_Specific, status_code=409, field="x", message="specific")
    register_form_error(_StubError, status_code=422, field="y", message="base")
    mapping = lookup_form_error(_Specific())
    assert mapping is not None
    assert mapping.message == "specific"


def test_builtin_registrations_cover_fastapi_users_exceptions():
    """Framework boot installs `UserAlreadyExists` and
    `InvalidPasswordException`. Pin them here so a refactor of the
    registry module can't silently lose the auth-flow defaults that
    the register/login routes depend on."""
    from fastapi_users import exceptions as fa_users_exceptions

    # Use a stub exception to dodge __init__ argument requirements.
    stub_uae = fa_users_exceptions.UserAlreadyExists.__new__(
        fa_users_exceptions.UserAlreadyExists
    )
    stub_ipe = fa_users_exceptions.InvalidPasswordException.__new__(
        fa_users_exceptions.InvalidPasswordException
    )
    # InvalidPasswordException's message_from reads .reason; set it.
    stub_ipe.reason = "too short"

    uae_fe = render_with_registry(stub_uae)
    assert uae_fe is not None
    assert uae_fe.status_code == 409
    assert "email" in uae_fe.field_errors

    ipe_fe = render_with_registry(stub_ipe)
    assert ipe_fe is not None
    assert ipe_fe.status_code == 422
    assert ipe_fe.field_errors == {"password": "too short"}
