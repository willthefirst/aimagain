"""The provider-agnostic observability contract.

Every backend in this package implements this Protocol. The rest of the
codebase imports `observability` from `__init__.py` (an `ObservabilityBackend`
instance) and never imports a provider SDK directly — that's the seam that
lets us swap Sentry out without touching the call sites.
"""

from typing import Protocol, runtime_checkable

from fastapi import FastAPI


@runtime_checkable
class ObservabilityBackend(Protocol):
    """Error tracking + performance tracing contract.

    Kept deliberately small: anything bigger ties the abstraction to a
    specific provider's feature set. Provider-specific knobs (sample
    rates, replay, etc.) belong in settings and the backend reads them
    directly — they don't surface here.
    """

    def init_app(self, app: FastAPI) -> None:
        """Install integrations + initialize the provider SDK.

        Called once from `src/main.py` during app construction. Idempotent
        backends are allowed but not required; callers must not call this
        twice.
        """
        ...

    def set_user(self, user_id: str, email: str | None = None) -> None:
        """Attach a user identity to the active request scope.

        Called from the auth dependencies in `src/auth_config.py` so that
        any error raised inside the handler carries the user. Tagging from
        middleware after `call_next` is too late — the exception has
        already been captured by then.
        """
        ...

    def frontend_context(self) -> dict | None:
        """Return the dict consumed by `base.html` to init the browser SDK.

        `None` means "no browser SDK loaded" (e.g. provider disabled, or
        a server-only backend). Concrete shape is provider-specific; the
        template branches on `provider`.
        """
        ...
