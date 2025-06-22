import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from src.models import User
from src.repositories.user_repository import UserRepository

from .exceptions import DatabaseError, ServiceError

logger = logging.getLogger(__name__)


class PresenceService:
    def __init__(self, user_repository: UserRepository):
        self.user_repo = user_repository
        self.session = user_repository.session

    async def update_user_presence(self, user_id: UUID) -> None:
        """Update user's last_active_at timestamp and set them as online."""
        try:
            now = datetime.now(timezone.utc)

            stmt = (
                update(User)
                .where(User.id == user_id)
                .values(
                    last_active_at=now,
                    is_online=True,
                )
            )

            await self.session.execute(stmt)
            await self.session.commit()

        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.warning(f"Database error updating presence for user {user_id}: {e}")
            raise DatabaseError(f"Failed to update presence for user {user_id}")
        except Exception as e:
            await self.session.rollback()
            logger.error(
                f"Unexpected error updating presence for user {user_id}: {e}",
                exc_info=True,
            )
            raise ServiceError(
                f"An unexpected error occurred while updating user presence"
            )

    async def update_all_users_online_status(
        self, online_timeout_minutes: int = 5
    ) -> None:
        """Update is_online status for all users based on their last_active_at timestamp."""
        try:
            now = datetime.now(timezone.utc)
            online_cutoff = now - timedelta(minutes=online_timeout_minutes)

            # Update users to online if they were active within the timeout
            online_stmt = (
                update(User)
                .where(User.last_active_at >= online_cutoff)
                .values(is_online=True)
            )
            await self.session.execute(online_stmt)

            # Update users to offline if they were not active within the timeout
            # or have no last_active_at timestamp
            offline_stmt = (
                update(User)
                .where(
                    (User.last_active_at < online_cutoff)
                    | (User.last_active_at.is_(None))
                )
                .values(is_online=False)
            )
            await self.session.execute(offline_stmt)

            await self.session.commit()

        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(
                f"Database error updating all users online status: {e}", exc_info=True
            )
            raise DatabaseError(
                "Failed to update all users online status due to a database error"
            )
        except Exception as e:
            await self.session.rollback()
            logger.error(
                f"Unexpected error updating all users online status: {e}", exc_info=True
            )
            raise ServiceError(
                "An unexpected error occurred while updating all users online status"
            )
