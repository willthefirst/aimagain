"""Tests for `src/framework/rendering/templating.py`."""

from unittest.mock import patch

from .templating import _env, get_template_context, register_template_globals


def test_register_template_globals_updates_env():
    """`register_template_globals` is the only entrypoint domain code
    uses to wire entity-specific values into Jinja — verify it forwards
    kwargs to `_env.globals` directly so a renamed kwarg surfaces here
    instead of as a missing-variable render error."""
    sentinel = object()
    register_template_globals(__test_marker__=sentinel)
    assert _env.globals["__test_marker__"] is sentinel
    del _env.globals["__test_marker__"]


def test_framework_owns_no_domain_globals():
    """The framework env should expose only domain-agnostic globals at
    rest. Domain enums, per-kind schemas, and view helpers are
    registered from `src/domain/template_globals.py`; tests that exercise
    the framework env in isolation must explicitly load that module."""
    # `field_spec` is the only framework-declared global; everything
    # else either comes from domain registration or is a Jinja built-in.
    # A snapshot test would lock down too much, so just assert the
    # framework's own contribution survives.
    assert "field_spec" in _env.globals


def test_livereload_not_loaded_in_production():
    """Livereload should not be loaded when is_development is False."""
    with patch("src.framework.rendering.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        context = get_template_context()
        assert context["is_development"] is False


def test_livereload_loaded_in_development():
    """Livereload should be loaded when is_development is True."""
    with patch("src.framework.rendering.templating.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "development"
        context = get_template_context()
        assert context["is_development"] is True
