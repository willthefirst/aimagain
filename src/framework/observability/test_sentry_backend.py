"""Tests for `sentry_backend.py`.

We patch `sentry_sdk` rather than touching the real SDK so the test
process doesn't open a network connection or carry state between tests.
The contract under test is "settings → SDK init kwargs", "user payload
shape", "frontend_context dict shape" — not the SDK's internals.
"""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from .sentry_backend import SentryBackend


def test_init_app_calls_sentry_init_with_settings():
    with (
        patch("src.framework.observability.sentry_backend.sentry_sdk") as mock_sdk,
        patch("src.framework.observability.sentry_backend.settings") as mock_settings,
    ):
        mock_settings.SENTRY_DSN = "https://abc@sentry.io/1"
        mock_settings.ENVIRONMENT = "production"
        mock_settings.APP_RELEASE = "deadbeef"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.25
        mock_settings.SENTRY_PROFILES_SAMPLE_RATE = 0.5

        SentryBackend().init_app(FastAPI())

        mock_sdk.init.assert_called_once()
        kwargs = mock_sdk.init.call_args.kwargs
        assert kwargs["dsn"] == "https://abc@sentry.io/1"
        assert kwargs["environment"] == "production"
        assert kwargs["release"] == "deadbeef"
        assert kwargs["traces_sample_rate"] == 0.25
        assert kwargs["profile_session_sample_rate"] == 0.5
        assert kwargs["send_default_pii"] is True


def test_init_app_passes_release_as_none_when_unset():
    """Empty `APP_RELEASE` must become `release=None` so events from
    un-tagged builds don't cluster under a synthetic empty-string
    release in the Sentry UI."""
    with (
        patch("src.framework.observability.sentry_backend.sentry_sdk") as mock_sdk,
        patch("src.framework.observability.sentry_backend.settings") as mock_settings,
    ):
        mock_settings.SENTRY_DSN = "https://abc@sentry.io/1"
        mock_settings.ENVIRONMENT = "production"
        mock_settings.APP_RELEASE = ""
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        mock_settings.SENTRY_PROFILES_SAMPLE_RATE = 0.1

        SentryBackend().init_app(FastAPI())

        assert mock_sdk.init.call_args.kwargs["release"] is None


def test_init_app_skips_sdk_init_when_backend_dsn_empty():
    """SentryBackend may be selected (e.g. browser-only DSN set) without a
    backend DSN. In that case `init_app` must not call `sentry_sdk.init` —
    passing an empty DSN would disable or misconfigure the SDK silently."""
    with (
        patch("src.framework.observability.sentry_backend.sentry_sdk") as mock_sdk,
        patch("src.framework.observability.sentry_backend.settings") as mock_settings,
    ):
        mock_settings.SENTRY_DSN = ""

        SentryBackend().init_app(FastAPI())

        mock_sdk.init.assert_not_called()


def test_set_user_includes_email_when_provided():
    with patch("src.framework.observability.sentry_backend.sentry_sdk") as mock_sdk:
        mock_sdk.set_user = MagicMock()
        SentryBackend().set_user("uid-1", "u@example.com")
        mock_sdk.set_user.assert_called_once_with(
            {"id": "uid-1", "email": "u@example.com"}
        )


def test_set_user_omits_email_when_none():
    """Passing `email=None` shouldn't ship a literal `None` to Sentry —
    drop the key so the UI doesn't render a blank email field."""
    with patch("src.framework.observability.sentry_backend.sentry_sdk") as mock_sdk:
        mock_sdk.set_user = MagicMock()
        SentryBackend().set_user("uid-1", None)
        mock_sdk.set_user.assert_called_once_with({"id": "uid-1"})


def test_frontend_context_shape():
    """The dict that lands in `base.html`. Uses `SENTRY_BROWSER_DSN` (the
    frontend project), not `SENTRY_DSN` (backend). Keys checked exhaustively
    so a rename here forces a template + test update."""
    with patch("src.framework.observability.sentry_backend.settings") as mock_settings:
        mock_settings.SENTRY_BROWSER_DSN = "https://xyz@sentry.io/2"
        mock_settings.ENVIRONMENT = "production"
        mock_settings.APP_RELEASE = "deadbeef"
        mock_settings.SENTRY_TRACES_SAMPLE_RATE = 0.1
        mock_settings.SENTRY_REPLAY_SAMPLE_RATE = 0.0
        mock_settings.SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE = 0.0

        ctx = SentryBackend().frontend_context()

    assert ctx == {
        "provider": "sentry",
        "dsn": "https://xyz@sentry.io/2",
        "environment": "production",
        "release": "deadbeef",
        "traces_sample_rate": 0.1,
        "replays_session_sample_rate": 0.0,
        "replays_on_error_sample_rate": 0.0,
    }


def test_frontend_context_returns_none_when_browser_dsn_unset():
    """No browser DSN → no browser SDK. Returns `None` so `base.html`'s
    `{% if observability_frontend %}` guard suppresses the script tag."""
    with patch("src.framework.observability.sentry_backend.settings") as mock_settings:
        mock_settings.SENTRY_BROWSER_DSN = ""

        ctx = SentryBackend().frontend_context()

    assert ctx is None
