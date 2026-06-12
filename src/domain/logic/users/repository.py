from typing import Sequence

from sqlalchemy import select

from src.domain.models import User
from src.framework.persistence.base_repository import BaseRepository
from src.framework.persistence.dependencies import register_repository


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

    async def list_users(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> Sequence[User]:
        """Directory listing — privacy-scoped.

        Non-admin viewers see exactly their own row; superusers see every
        user. `handle_list` stamps the viewer onto `self._requesting_user`
        before calling this method (see
        `src/framework/dispatch/mounts/list_.py`), so the filter is a
        plain WHERE clause — no extra dep wiring needed.
        """
        viewer = self._requesting_user
        stmt = select(User)
        if viewer is None or not viewer.is_superuser:
            viewer_id = viewer.id if viewer is not None else None
            stmt = stmt.filter(User.id == viewer_id)
        stmt = stmt.order_by(User.username)
        return await self._list(stmt, offset=offset, limit=limit)

    async def delete_user(self, user: User) -> None:
        """Hard-deletes the user row; the caller commits."""
        await self._delete(user)


get_user_repository = register_repository(UserRepository)
