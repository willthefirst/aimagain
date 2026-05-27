"""Provider-agnostic error tracking + performance tracing.

Public surface:
  - `observability.init_app(app)` — install integrations. Called once
    from `src/main.py` at app construction.
  - `observability.set_user(user_id, email)` — tag the active request
    scope. Called from the wrapping auth dependencies in
    `src/auth_config.py` so errors raised inside the handler carry the
    user (the older middleware-after-`call_next` pattern was a no-op for
    exceptions).
  - `observability.frontend_context()` — dict (or `None`) consumed by
    `base.html` to init the browser SDK.

Swapping providers is a code change in this directory only:
  1. Add `*_backend.py` implementing `ObservabilityBackend`.
  2. Branch in `_select_backend()` below.
  3. Add the provider's init snippet in `base.html` next to the existing
     Sentry branch and key it off `observability_frontend.provider`.
"""

from src.framework.config import settings
from src.framework.observability.backend import ObservabilityBackend
from src.framework.observability.noop_backend import NoopBackend
from src.framework.observability.sentry_backend import SentryBackend


def _select_backend() -> ObservabilityBackend:
    """Pick a backend from settings.

    Either DSN set → `SentryBackend`; `init_app` skips SDK init when
    `SENTRY_DSN` is empty, `frontend_context` returns None when
    `SENTRY_BROWSER_DSN` is empty — each side is independently optional.
    Both empty → `NoopBackend` so the app runs locally with no provider.
    Add new providers as additional branches.
    """
    if settings.SENTRY_DSN or settings.SENTRY_BROWSER_DSN:
        return SentryBackend()
    return NoopBackend()


observability: ObservabilityBackend = _select_backend()


__all__ = ["ObservabilityBackend", "observability"]
