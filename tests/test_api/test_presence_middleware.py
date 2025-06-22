from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from src.middleware.presence import update_all_users_online_status
from src.models import User


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


async def test_middleware_updates_is_online_status(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test middleware updates is_online status on authenticated requests"""
    # Ensure user starts as offline
    async with db_test_session_manager() as session:
        user = await session.get(User, logged_in_user.id)
        user.is_online = False
        await session.commit()

    # Make any authenticated request
    response = await authenticated_client.get("/conversations")
    assert response.status_code == 200

    # Check that user's is_online was updated to True
    async with db_test_session_manager() as session:
        updated_user = await session.get(User, logged_in_user.id)
        assert updated_user.is_online is True


async def test_middleware_ignores_unauthenticated_requests(test_client: AsyncClient):
    """Test middleware doesn't affect unauthenticated requests"""
    # This should not raise any errors and should work normally
    response = await test_client.get("/")
    assert response.status_code == 302


async def test_middleware_handles_database_errors_gracefully(
    authenticated_client: AsyncClient, logged_in_user: User
):
    """Test middleware doesn't break app if presence update fails"""
    with patch(
        "src.middleware.presence.PresenceMiddleware._do_presence_update",
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


async def test_update_all_users_online_status_with_recent_activity(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test that users with recent activity are marked as online"""
    # Create test users
    async with db_test_session_manager() as session:
        # User with recent activity (should be online)
        recent_user = create_test_user(username="recent_user")
        recent_user.last_active_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_user.is_online = False  # Start as offline
        session.add(recent_user)

        # User with old activity (should be offline)
        old_user = create_test_user(username="old_user")
        old_user.last_active_at = datetime.now(timezone.utc) - timedelta(minutes=15)
        old_user.is_online = True  # Start as online
        session.add(old_user)

        # User with no activity (should be offline)
        no_activity_user = create_test_user(username="no_activity_user")
        no_activity_user.last_active_at = None
        no_activity_user.is_online = True  # Start as online
        session.add(no_activity_user)

        await session.commit()

        # Run the update function with the session
        await update_all_users_online_status(session)

        # Check results
        recent_user_updated = await session.get(User, recent_user.id)
        old_user_updated = await session.get(User, old_user.id)
        no_activity_user_updated = await session.get(User, no_activity_user.id)

        assert recent_user_updated.is_online is True  # Should be online
        assert old_user_updated.is_online is False  # Should be offline
        assert no_activity_user_updated.is_online is False  # Should be offline


async def test_update_all_users_online_status_respects_timeout_config(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test that the online status update respects the configured timeout"""
    from src.core.config import settings

    # Create a user with activity exactly at the timeout boundary
    async with db_test_session_manager() as session:
        boundary_user = create_test_user(username="boundary_user")
        # Set activity exactly at the timeout (should be offline)
        boundary_user.last_active_at = datetime.now(timezone.utc) - timedelta(
            minutes=settings.ONLINE_TIMEOUT_MINUTES + 1
        )
        boundary_user.is_online = True  # Start as online
        session.add(boundary_user)

        # User just within the timeout (should be online)
        within_user = create_test_user(username="within_user")
        within_user.last_active_at = datetime.now(timezone.utc) - timedelta(
            minutes=settings.ONLINE_TIMEOUT_MINUTES - 1
        )
        within_user.is_online = False  # Start as offline
        session.add(within_user)

        await session.commit()

        # Run the update function with the session
        await update_all_users_online_status(session)

        # Check results
        boundary_user_updated = await session.get(User, boundary_user.id)
        within_user_updated = await session.get(User, within_user.id)

        assert boundary_user_updated.is_online is False  # Should be offline
        assert within_user_updated.is_online is True  # Should be online


async def test_update_all_users_online_status_handles_errors_gracefully(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test that update_all_users_online_status handles database errors gracefully"""
    # Test with a real database error scenario
    with patch("src.middleware.presence.logger") as mock_logger:
        # Create a scenario where the database operation fails
        async def failing_execute(*args, **kwargs):
            raise Exception("Database operation failed")

        async with db_test_session_manager() as session:
            # Mock the session's execute method to fail
            with patch.object(session, "execute", side_effect=failing_execute):
                # The service catches the original exception and raises a ServiceError
                from src.services.exceptions import ServiceError

                with pytest.raises(
                    ServiceError,
                    match="An unexpected error occurred while updating all users online status",
                ):
                    await update_all_users_online_status(session)

                # Should have logged the error
                mock_logger.warning.assert_called()
