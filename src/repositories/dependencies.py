from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db_session

from .audit.audit_repository import AuditRepository
from .posts.post_repository import PostRepository
from .providers.provider_repository import ProviderRepository
from .users.user_repository import UserRepository


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


def get_provider_repository(
    session: AsyncSession = Depends(get_db_session),
) -> ProviderRepository:
    """Dependency provider for ProviderRepository."""
    return ProviderRepository(session)
