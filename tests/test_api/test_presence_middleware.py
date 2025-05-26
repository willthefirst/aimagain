from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from app.models import User


async def test_middleware_updates_presence_for_authenticated_user(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test middleware updates last_active_at on authenticated requests"""
    # Record time before request
    before_request = datetime.now(timezone.utc)

    # Make any authenticated request
    response = await authenticated_client.get("/conversations")
    assert response.status_code == 200

    # Check that user's last_active_at was updated
    async with db_test_session_manager() as session:
        updated_user = await session.get(User, logged_in_user.id)
        assert updated_user.last_active_at is not None

        # Handle timezone-naive datetime from database
        last_active = updated_user.last_active_at
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)

        assert last_active >= before_request
        assert last_active <= datetime.now(timezone.utc)


async def test_middleware_ignores_unauthenticated_requests(test_client: AsyncClient):
    """Test middleware doesn't affect unauthenticated requests"""
    # This should not raise any errors and should work normally
    response = await test_client.get("/")
    assert response.status_code == 200


async def test_middleware_handles_database_errors_gracefully(
    authenticated_client: AsyncClient, logged_in_user: User
):
    """Test middleware doesn't break app if presence update fails"""
    with patch(
        "app.middleware.presence.update_user_presence",
        side_effect=Exception("DB Error"),
    ):
        # Request should still succeed even if presence update fails
        response = await authenticated_client.get("/conversations")
        assert response.status_code == 200


async def test_middleware_updates_on_multiple_requests(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test subsequent requests update the timestamp"""
    # First request
    response1 = await authenticated_client.get("/conversations")
    assert response1.status_code == 200

    async with db_test_session_manager() as session:
        user_after_first = await session.get(User, logged_in_user.id)
        first_timestamp = user_after_first.last_active_at
        assert first_timestamp is not None

    # Wait a tiny bit to ensure timestamp difference
    import asyncio

    await asyncio.sleep(0.01)

    # Second request
    response2 = await authenticated_client.get("/users")
    assert response2.status_code == 200

    async with db_test_session_manager() as session:
        user_after_second = await session.get(User, logged_in_user.id)
        second_timestamp = user_after_second.last_active_at
        assert second_timestamp is not None
        assert second_timestamp >= first_timestamp


async def test_middleware_only_updates_on_successful_requests(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test middleware only updates presence on successful (2xx/3xx) responses"""
    # Make a request that should fail (non-existent conversation)
    response = await authenticated_client.get("/conversations/nonexistent-slug")
    assert response.status_code >= 400  # Should be 404 or 403

    # Check that user's last_active_at was NOT updated (should still be None)
    async with db_test_session_manager() as session:
        user = await session.get(User, logged_in_user.id)
        # Since this is the first request and it failed, last_active_at should still be None
        assert user.last_active_at is None
