from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user


async def test_user_has_last_active_at_field(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test that User model has last_active_at timestamp field"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            user.last_active_at = datetime.now(timezone.utc)
            session.add(user)
            await session.flush()

            assert user.last_active_at is not None
            assert isinstance(user.last_active_at, datetime)


async def test_user_has_is_online_field(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test that User model has is_online boolean field"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()

            assert hasattr(user, "is_online")
            assert isinstance(user.is_online, bool)


async def test_is_online_defaults_to_false(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test new users have is_online=False initially"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()

            assert user.is_online is False


async def test_last_active_at_defaults_to_null(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test new users have null last_active_at initially"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()

            assert user.last_active_at is None


async def test_can_update_last_active_at(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test updating last_active_at timestamp"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()
            user_id = user.id

            # Update last_active_at
            new_time = datetime.now(timezone.utc)
            user.last_active_at = new_time
            await session.flush()

            assert user.last_active_at == new_time


async def test_can_update_is_online_status(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test updating is_online status"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()

            # Update is_online to True
            user.is_online = True
            await session.flush()
            assert user.is_online is True

            # Update is_online back to False
            user.is_online = False
            await session.flush()
            assert user.is_online is False


async def test_can_update_both_presence_fields_together(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test updating both last_active_at and is_online together"""
    async with db_test_session_manager() as session:
        async with session.begin():
            user = create_test_user()
            session.add(user)
            await session.flush()

            # Update both fields
            new_time = datetime.now(timezone.utc)
            user.last_active_at = new_time
            user.is_online = True
            await session.flush()

            assert user.last_active_at == new_time
            assert user.is_online is True
