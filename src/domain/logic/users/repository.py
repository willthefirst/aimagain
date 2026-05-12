from sqlalchemy import select

from src.domain.models import User
from src.framework.base_repository import BaseRepository


class UserRepository(BaseRepository):
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

    async def delete_user(self, user: User) -> None:
        """Hard-deletes the user row; the caller commits."""
        await self._delete(user)
