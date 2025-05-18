import logging

from sqlalchemy.exc import SQLAlchemyError

from app.models import Conversation, Participant, User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.participant_repository import ParticipantRepository

from .exceptions import DatabaseError, ServiceError

logger = logging.getLogger(__name__)


class UserService:
    def __init__(
        self,
        participant_repository: ParticipantRepository,
        conversation_repository: ConversationRepository,
    ):
        self.part_repo = participant_repository
        self.conv_repo = conversation_repository

    async def get_user_invitations(self, user: User) -> list[Participant]:
        """Fetches pending invitations for the given user."""
        try:
            return await self.part_repo.list_user_invitations(user=user)
        except SQLAlchemyError as e:
            logger.error(
                f"Database error fetching invitations for user {user.id}: {e}",
                exc_info=True,
            )
            raise DatabaseError(
                "Failed to fetch user invitations due to a database error."
            )
        except Exception as e:
            logger.error(
                f"Unexpected error fetching invitations for user {user.id}: {e}",
                exc_info=True,
            )
            raise ServiceError(
                "An unexpected error occurred while fetching invitations."
            )

    async def get_user_conversations(self, user: User) -> list[Conversation]:
        """Fetches conversations the given user is a participant in."""
        try:
            return await self.conv_repo.list_user_conversations(user=user)
        except SQLAlchemyError as e:
            logger.error(
                f"Database error fetching conversations for user {user.id}: {e}",
                exc_info=True,
            )
            raise DatabaseError(
                "Failed to fetch user conversations due to a database error."
            )
        except Exception as e:
            logger.error(
                f"Unexpected error fetching conversations for user {user.id}: {e}",
                exc_info=True,
            )
            raise ServiceError(
                "An unexpected error occurred while fetching conversations."
            )
