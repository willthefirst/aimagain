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
