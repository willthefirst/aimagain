from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session

from .user_repository import UserRepository


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepository:
    """Dependency provider for UserRepository."""
    return UserRepository(session)
