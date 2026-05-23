"""No-op backend used when no provider is configured.

Lets every call site invoke `observability.set_user(...)` etc.
unconditionally without paying a `if settings.SENTRY_DSN` guard at each
site. Selected by `_select_backend()` in `__init__.py` when the
provider's DSN/key is empty.
"""

from fastapi import FastAPI


class NoopBackend:
    def init_app(self, app: FastAPI) -> None:
        return

    def set_user(self, user_id: str, email: str | None = None) -> None:
        return

    def frontend_context(self) -> dict | None:
        return None
