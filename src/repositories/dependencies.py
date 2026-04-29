from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session

from .post_repository import PostRepository
from .user_repository import UserRepository


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """Dependency provider for UserRepository."""
    return UserRepository(session)


def get_post_repository(
    session: AsyncSession = Depends(get_db_session),
) -> PostRepository:
    """Dependency provider for PostRepository."""
    return PostRepository(session)
