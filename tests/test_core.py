"""Tests for the core module configuration and templating."""

import os
from unittest.mock import patch

from src.core.config import Settings
from src.core.templating import get_template_context


def test_environment_defaults_to_production():
    """ENVIRONMENT should default to production for safety.

    This prevents dev tools (like livereload) from accidentally loading
    in production if the ENVIRONMENT variable is not explicitly set.
    """
    # Create a Settings object with empty env vars
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


def test_livereload_not_loaded_in_production():
    """Livereload should not be loaded when is_development is False."""
    with patch("src.core.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        context = get_template_context()
        assert context["is_development"] is False


def test_livereload_loaded_in_development():
    """Livereload should be loaded when is_development is True."""
    with patch("src.core.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        context = get_template_context()
        assert context["is_development"] is True
