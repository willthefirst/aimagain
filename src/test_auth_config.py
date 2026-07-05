"""Tests for the observability-tagging wrappers around fastapi-users deps.

The wrappers in `src/auth_config.py` are the only place we tag the
observability scope with a user. If a refactor accidentally drops the
`observability.set_user(...)` call, every error in prod loses its user
context — pin that here.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from . import auth_config


@pytest.mark.asyncio
async def test_current_active_user_tags_observability():
    user = SimpleNamespace(id="uid-1", email="u@example.com")
    with patch.object(auth_config, "observability") as mock_obs:
        mock_obs.set_user = MagicMock()
        result = await auth_config.current_active_user(user=user)
    assert result is user
    mock_obs.set_user.assert_called_once_with("uid-1", "u@example.com")


@pytest.mark.asyncio
async def test_current_admin_user_tags_observability():
    user = SimpleNamespace(id="uid-2", email="admin@example.com")
    with patch.object(auth_config, "observability") as mock_obs:
        mock_obs.set_user = MagicMock()
        result = await auth_config.current_admin_user(user=user)
    assert result is user
    mock_obs.set_user.assert_called_once_with("uid-2", "admin@example.com")


@pytest.mark.asyncio
async def test_current_optional_user_tags_only_when_present():
    """Anonymous requests must not inherit a stale identity. When the
    optional dep returns `None`, `set_user` must not be called."""
    with patch.object(auth_config, "observability") as mock_obs:
        mock_obs.set_user = MagicMock()
        result = await auth_config.current_optional_user(user=None)
    assert result is None
    mock_obs.set_user.assert_not_called()


@pytest.mark.asyncio
async def test_current_optional_user_tags_when_present():
    user = SimpleNamespace(id="uid-3", email="opt@example.com")
    with patch.object(auth_config, "observability") as mock_obs:
        mock_obs.set_user = MagicMock()
        result = await auth_config.current_optional_user(user=user)
    assert result is user
    mock_obs.set_user.assert_called_once_with("uid-3", "opt@example.com")


def _login_manager() -> auth_config.UserManager:
    """A `UserManager` whose `__init__` we bypass — `on_after_login`
    only touches `request`/`response`, never instance state."""
    return auth_config.UserManager.__new__(auth_config.UserManager)


@pytest.mark.asyncio
async def test_on_after_login_defaults_to_referral_board():
    """No `?next=` → post-login lands on the referral board
    (`/posts?kind=referral`), the signed-in "home", in lockstep with
    `src/main.py:read_root`'s authed `/` redirect target."""
    request = SimpleNamespace(query_params={})
    response = SimpleNamespace(status_code=None, headers={})
    await _login_manager().on_after_login(
        user=SimpleNamespace(id="uid"), request=request, response=response
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/posts?kind=referral"


@pytest.mark.asyncio
async def test_on_after_login_honors_safe_next_param():
    """A relative `?next=` overrides the referral-board default so an auth
    wall can bounce the user back to where they were headed."""
    request = SimpleNamespace(query_params={"next": "/users/me"})
    response = SimpleNamespace(status_code=None, headers={})
    await _login_manager().on_after_login(
        user=SimpleNamespace(id="uid"), request=request, response=response
    )
    assert response.headers["Location"] == "/users/me"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evil_next", ["//evil.com", "https://evil.com", "javascript://x"]
)
async def test_on_after_login_rejects_offsite_next(evil_next: str):
    """Protocol-relative / absolute `next` values are ignored — they
    could redirect to an attacker site — falling back to the referral
    board."""
    request = SimpleNamespace(query_params={"next": evil_next})
    response = SimpleNamespace(status_code=None, headers={})
    await _login_manager().on_after_login(
        user=SimpleNamespace(id="uid"), request=request, response=response
    )
    assert response.headers["Location"] == "/posts?kind=referral"
