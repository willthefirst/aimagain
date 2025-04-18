import logging
from sqlalchemy.exc import SQLAlchemyError

from app.models import User, Participant, Conversation
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.conversation_repository import ConversationRepository

# Import shared service exceptions
from .exceptions import (
    ServiceError,
    DatabaseError,
    # Import others like UserNotFoundError if needed for future methods
)

logger = logging.getLogger(__name__)


class UserService:
    def __init__(
        self,
        participant_repository: ParticipantRepository,
        conversation_repository: ConversationRepository,
        # Note: We don't strictly need UserRepository for these specific methods
        # as the User object is already provided by the auth dependency.
        # Add it if other user-related service methods require it.
    ):
        self.part_repo = participant_repository
        self.conv_repo = conversation_repository
        # No direct session needed if only doing reads via repos

    # Profile data is just the User object from the dependency, no service method needed for that yet.

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
