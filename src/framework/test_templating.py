"""Tests for `src/core/templating.py`."""

from unittest.mock import patch

from .templating import get_template_context


def test_livereload_not_loaded_in_production():
    """Livereload should not be loaded when is_development is False."""
    with patch("src.framework.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        context = get_template_context()
        assert context["is_development"] is False


def test_livereload_loaded_in_development():
    """Livereload should be loaded when is_development is True."""
    with patch("src.framework.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        context = get_template_context()
        assert context["is_development"] is True
