from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User

from .base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Retrieves a user by their ID."""
        stmt = select(User).filter(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_user_by_username(self, username: str) -> User | None:
        """Retrieves a user by their username."""
        stmt = select(User).filter(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_user_by_email(self, email: str) -> User | None:
        """Retrieves a user by their email address."""
        stmt = select(User).filter(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_users(
        self,
        *,
        exclude_user: User | None = None,
    ) -> Sequence[User]:
        """Lists users, optionally excluding a user."""
        stmt = select(User)

        if exclude_user:
            stmt = stmt.filter(User.id != exclude_user.id)

        stmt = stmt.order_by(User.username)
        result = await self.session.execute(stmt)
        return result.scalars().all()
