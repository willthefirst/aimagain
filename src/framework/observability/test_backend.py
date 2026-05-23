"""Tests for the backend factory in `src/framework/observability/__init__.py`.

The factory's job is just "pick the right backend from settings." We
test that here so a regression — e.g. silently falling through to Noop
when a DSN is set — surfaces immediately.
"""

from unittest.mock import patch

from .backend import ObservabilityBackend
from .noop_backend import NoopBackend
from .sentry_backend import SentryBackend


def _import_factory():
    """Pull `_select_backend` lazily so each test sees the patched settings."""
    from . import _select_backend

    return _select_backend


def test_select_backend_returns_sentry_when_dsn_set():
    with patch("src.framework.observability.settings") as mock_settings:
        mock_settings.SENTRY_DSN = "https://abc@sentry.io/1"
        backend = _import_factory()()
    assert isinstance(backend, SentryBackend)


def test_select_backend_returns_noop_when_dsn_empty():
    with patch("src.framework.observability.settings") as mock_settings:
        mock_settings.SENTRY_DSN = ""
        backend = _import_factory()()
    assert isinstance(backend, NoopBackend)


def test_concrete_backends_satisfy_protocol():
    """Both backends must structurally satisfy `ObservabilityBackend` so
    call sites typed against the Protocol never need a provider-specific
    branch."""
    assert isinstance(NoopBackend(), ObservabilityBackend)
    # SentryBackend doesn't init the SDK at construction, only on
    # `init_app`, so it's cheap to instantiate here.
    assert isinstance(SentryBackend(), ObservabilityBackend)
