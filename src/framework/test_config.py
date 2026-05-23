"""Tests for `src/framework/config.py`."""

import os
from unittest.mock import patch

from .config import Settings


def test_environment_defaults_to_production():
    """ENVIRONMENT should default to production for safety.

    This prevents dev tools (like livereload) from accidentally loading
    in production if the ENVIRONMENT variable is not explicitly set.
    """
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.ENVIRONMENT == "production"


def test_environment_can_be_set_to_development():
    """ENVIRONMENT can be explicitly set to development."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        settings = Settings(
            SECRET="test",
            DATABASE_URL="postgresql://test",
            ENVIRONMENT="development",
        )
        assert settings.ENVIRONMENT == "development"


def test_observability_defaults_are_quota_safe():
    """Sample-rate defaults are pinned because a regression to `1.0`
    (the SDK's default) would silently 10× the Sentry bill on prod
    traffic. Replay defaults to off — it's a paid add-on."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(SECRET="test", DATABASE_URL="postgresql://test")
        assert settings.SENTRY_DSN == ""
        assert settings.SENTRY_TRACES_SAMPLE_RATE == 0.1
        assert settings.SENTRY_PROFILES_SAMPLE_RATE == 0.1
        assert settings.SENTRY_REPLAY_SAMPLE_RATE == 0.0
        assert settings.SENTRY_REPLAY_ON_ERROR_SAMPLE_RATE == 0.0
        assert settings.APP_RELEASE == ""
