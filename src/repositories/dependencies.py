from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session

from .audit_repository import AuditRepository
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


def get_audit_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AuditRepository:
    """Dependency provider for AuditRepository."""
    return AuditRepository(session)
