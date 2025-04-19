from typing import Sequence
from sqlalchemy import select, exists, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseRepository
from app.models import User, Participant


class UserRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Retrieves a user by their ID."""
        stmt = select(User).filter(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_user_by_username(self, username: str) -> User | None:
        """Retrieves a user by their username.
        Note: Used temporarily for placeholder auth checks.
        """
        stmt = select(User).filter(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_users(
        self,
        *,
        exclude_user: User | None = None,
        participated_with_user: User | None = None,
    ) -> Sequence[User]:
        """Lists users, optionally excluding a user and filtering by participation.

        Args:
            exclude_user: If provided, this user will be excluded from the results.
            participated_with_user: If provided, only lists users who have participated
                                     in a joined conversation with this user.
        """
        stmt = select(User)

        if participated_with_user:
            # Find conversations the target user is joined in
            joined_conv_subq = (
                select(Participant.conversation_id).where(
                    Participant.user_id == participated_with_user.id,
                    Participant.status == "joined",
                )
                # Use scalar_subquery() for use within IN clause
                .scalar_subquery()
            )
            # Find users who are also joined in those conversations (excluding the target user)
            participating_user_ids_stmt = (
                select(Participant.user_id)
                .where(
                    # Check against the scalar subquery
                    Participant.conversation_id.in_(joined_conv_subq),
                    Participant.user_id != participated_with_user.id,
                    Participant.status == "joined",
                )
                .distinct()
            )
            # Filter the main user query by these IDs (use the statement directly)
            stmt = stmt.filter(User.id.in_(participating_user_ids_stmt))

        # Apply exclusion filter
        if exclude_user:
            stmt = stmt.filter(User.id != exclude_user.id)

        stmt = stmt.order_by(User.username)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # TODO: Add list_users method needed for users.py route
