"""`FormErrorRegistry` — exception type ⇒ form-error rendering rules.

Routes declared with `@form_error_handler` used to write a full lambda
per exception:

    handlers={
        UserAlreadyExists: lambda e: FormError(
            field_errors={"email": "An account with this email already exists."},
            status_code=409,
        ),
        InvalidPasswordException: lambda e: FormError(
            field_errors={"password": e.reason},
            status_code=422,
        ),
    }

Three of those facts aren't really route-specific:

  - **status code per exception type** — `UserAlreadyExists` is *always*
    a 409 Conflict, wherever it's raised; `InvalidPasswordException` is
    *always* a 422.
  - **field name per exception type** — `UserAlreadyExists` always
    points at `email`; `InvalidPasswordException` always points at
    `password`. The exception type *is* the field.
  - **default message** — the user-visible copy can be standardized too
    (an account-already-exists message doesn't change between
    `/auth/register` and a future admin-create-user flow).

This module holds the global registry. Framework boot registers the
fastapi-users exceptions; domain layers can register their own typed
exceptions the same way. `@form_error_handler` learns a
`catches=(ExceptionType, ...)` kwarg that pulls the rendering rules
from this registry — no per-route lambda needed when the defaults are
right.

When a route needs a different message (e.g. a route-specific copy
edit), it still passes `handlers={...}` and the explicit handler wins
over the registry. Mixed mode is supported:

    @form_error_handler(
        template="auth/_register_form.html",
        catches=(UserAlreadyExists, InvalidPasswordException),
        handlers={
            SomeRouteSpecificError: lambda e: FormError(...),
        },
    )

The registry is *not* a domain concept; it's framework plumbing.
fastapi-users exceptions are registered here because they're the
cross-cutting auth-flow contract. Per-app exceptions register from the
domain layer at import time — typically next to the exception
definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi_users import exceptions as fa_users_exceptions

from src.framework.http.form_error_handler import FormError


@dataclass(frozen=True)
class FormErrorMapping:
    """Resolved rendering rules for one exception type.

    Either `field` (per-field error on a named input) or `banner`
    (form-level alert) — never both, never neither. Pinned in
    `register_form_error` so registry misuse fails at registration,
    not at the moment of rendering.

    `message` is the literal user-visible copy; `message_from` is a
    callable that extracts a message from the exception instance
    (used when the exception carries the policy detail, e.g.
    `InvalidPasswordException(reason="too short")`). Set one, not
    both — `message_from` wins when present.
    """

    status_code: int
    field: str | None = None
    banner: bool = False
    message: str | None = None
    message_from: Callable[[Exception], str] | None = None


_REGISTRY: dict[type[Exception], FormErrorMapping] = {}


def register_form_error(
    exc_type: type[Exception],
    *,
    status_code: int,
    field: str | None = None,
    banner: bool = False,
    message: str | None = None,
    message_from: Callable[[Exception], str] | None = None,
) -> None:
    """Register `exc_type` with the rules `@form_error_handler` will
    use when a route lists it under `catches=`.

    Args:
      exc_type: the exception class (subclasses match via isinstance).
      status_code: HTTP status code the rerender returns. Pick the
        right RFC 9110 code for the failure — 409 for conflicts,
        422 for validation-but-syntactically-valid, 401 for auth
        failures, 403 for authz failures.
      field: name of the form input this error pins to. Mutually
        exclusive with `banner=True` (registry contract — pinned by a
        runtime check below).
      banner: True if this error renders as a form-level alert with no
        specific field (login bad-creds case).
      message: literal user-visible message. Either this or
        `message_from` must be set.
      message_from: callable that builds the message from the exception
        instance, for exceptions that carry their own detail
        (`InvalidPasswordException.reason`).
    """
    if (field is None) == (banner is False):
        # `field=...` xor `banner=True` — both unset is a no-op
        # registration; both set is a contradiction.
        raise ValueError(
            f"register_form_error({exc_type.__name__}): exactly one of "
            f"`field=` or `banner=True` must be supplied. "
            f"`field` is for per-input errors; `banner` is for form-level "
            f"alerts with no single owning input."
        )
    if (message is None) == (message_from is None):
        raise ValueError(
            f"register_form_error({exc_type.__name__}): exactly one of "
            f"`message=` (literal) or `message_from=` (callable) must be "
            f"supplied. The first is for static copy; the second is for "
            f"exceptions that carry their own detail (e.g. "
            f"`InvalidPasswordException.reason`)."
        )
    _REGISTRY[exc_type] = FormErrorMapping(
        status_code=status_code,
        field=field,
        banner=banner,
        message=message,
        message_from=message_from,
    )


def lookup_form_error(exc: Exception) -> FormErrorMapping | None:
    """Return the registered mapping for `exc`, or None.

    Matches via isinstance so a subclass picks up a base-class
    registration. First match wins by dict-insertion order; register
    the most specific exception first.
    """
    for exc_type, mapping in _REGISTRY.items():
        if isinstance(exc, exc_type):
            return mapping
    return None


def render_with_registry(exc: Exception) -> FormError | None:
    """Convert `exc` to a `FormError` using the registry, or None if
    `exc` isn't registered. Equivalent to the lambda an explicit
    `handlers=` entry would have written by hand.

    Called by `form_error_handler` when a `catches=` entry matches.
    """
    mapping = lookup_form_error(exc)
    if mapping is None:
        return None
    message = (
        mapping.message_from(exc)
        if mapping.message_from is not None
        else mapping.message
    )
    assert message is not None  # registration contract pins this
    if mapping.banner:
        return FormError(banner=message, status_code=mapping.status_code)
    assert mapping.field is not None
    return FormError(
        field_errors={mapping.field: message},
        status_code=mapping.status_code,
    )


def _clear_for_testing() -> None:
    """Test helper — clears the registry between tests that mutate it.

    Production code never calls this. Tests register synthetic
    exception types and use this to reset state.
    """
    _REGISTRY.clear()
    _install_builtin_registrations()


# --- built-in registrations -----------------------------------------------
#
# fastapi-users exceptions get registered at module import time. The
# decorator's `catches=(UserAlreadyExists, ...)` resolves through here,
# so a route never has to know that `UserAlreadyExists` → 409 → email
# unless it wants to override.
#
# Per-domain exception registrations belong in the domain layer (next
# to the exception definition). Framework code stays free of domain
# coupling.


def _install_builtin_registrations() -> None:
    register_form_error(
        fa_users_exceptions.UserAlreadyExists,
        status_code=409,  # RFC 9110 §15.5.10 Conflict
        field="email",
        message="An account with this email already exists.",
    )
    register_form_error(
        fa_users_exceptions.InvalidPasswordException,
        status_code=422,  # RFC 9110 §15.5.21 Unprocessable Content
        field="password",
        # Pydantic-style: the exception carries the policy detail —
        # "Password should be at least 8 chars", etc.
        message_from=lambda e: getattr(e, "reason", "Invalid password."),
    )
    register_form_error(
        fa_users_exceptions.InvalidResetPasswordToken,
        # 410 Gone fits the failure mode end users see — "your link
        # doesn't work anymore" (RFC 9110 §15.5.11). A malformed/forged
        # token semantically maps closer to 400, but 410 is the
        # canonical "this URL used to work" code and the user-facing
        # copy treats both cases the same.
        status_code=410,
        banner=True,
        message=(
            "This reset link is invalid or has expired. "
            "Request a new one from the forgot-password page."
        ),
    )


_install_builtin_registrations()
