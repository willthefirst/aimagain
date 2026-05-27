"""Sentry implementation of the observability contract.

Reads all knobs from `settings` so swapping in another provider is a
matter of adding a sibling backend file and changing `_select_backend()`
in `__init__.py`. No other file in the codebase imports `sentry_sdk`
directly — this is the only place.
"""

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from src.framework.config import settings


class SentryBackend:
    def init_app(self, app: FastAPI) -> None:
        if not settings.SENTRY_DSN:
            return
        # `release=None` (rather than empty string) tells Sentry "no
        # release tag" — important so events from un-tagged builds don't
        # cluster into a synthetic "" release.
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            release=settings.APP_RELEASE or None,
            send_default_pii=True,
            enable_logs=True,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            profile_session_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
            profile_lifecycle="trace",
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
        )

    def set_user(self, user_id: str, email: str | None = None) -> None:
        payload: dict[str, str] = {"id": user_id}
        if email is not None:
            payload["email"] = email
        sentry_sdk.set_user(payload)

    def frontend_context(self) -> dict | None:
        if not settings.SENTRY_BROWSER_DSN:
            return None
        return {
            "provider": "sentry",
            "dsn": settings.SENTRY_BROWSER_DSN,
            "environment": settings.ENVIRONMENT,
            "release": settings.APP_RELEASE,
            "traces_sample_rate": settings.SENTRY_TRACES_SAMPLE_RATE,
            "replays_session_sample_rate": settings.SENTRY_REPLAY_SAMPLE_RATE,
            "replays_on_error_sample_rate": settings.SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE,
        }
