import uuid
from typing import Optional
from uuid import UUID  # Import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Need ORM models
from src.models import User


def create_test_user(
    id: Optional[UUID] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    hashed_password: Optional[str] = None,
    is_active: bool = True,  # Added fastapi-users default
    is_superuser: bool = False,  # Added fastapi-users default
    is_verified: bool = True,  # Added fastapi-users default
) -> User:
    """Creates a User instance with default values for testing."""
    unique_suffix = uuid.uuid4()
    return User(
        id=id or unique_suffix,
        username=username or f"testuser_{unique_suffix}",
        email=email or f"test_{unique_suffix}@example.com",
        hashed_password=hashed_password or f"password_{unique_suffix}",
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )


async def promote_to_admin(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    user_email: str,
) -> None:
    """Mutate a fixture-created user to is_superuser=True.

    Used by colocated tests that need an admin actor — the standard
    `authenticated_client` fixture creates a non-admin user, so tests that
    exercise admin-gated routes flip the bit on the existing user instead of
    reauthenticating as a different one.
    """
    async with db_test_session_manager() as session:
        async with session.begin():
            stmt = select(User).filter(User.email == user_email)
            result = await session.execute(stmt)
            user = result.scalars().first()
            assert user is not None, f"Test user {user_email} not found"
            user.is_superuser = True
