import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Participant, User
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.participant_repository import ParticipantRepository
from app.schemas.participant import ParticipantStatus

from .exceptions import (
    BusinessRuleError,
    ConflictError,
    DatabaseError,
    NotAuthorizedError,
    ParticipantNotFoundError,
    ServiceError,
)

logger = logging.getLogger(__name__)


class ParticipantService:
    def __init__(
        self,
        participant_repository: ParticipantRepository,
        conversation_repository: ConversationRepository,
    ):
        self.part_repo = participant_repository
        self.conv_repo = conversation_repository
        self.session = participant_repository.session

    async def update_invitation_status(
        self, participant_id: UUID, target_status: ParticipantStatus, current_user: User
    ) -> Participant:
        """
        Updates the status of an *invitation* (participant record owned by current_user
        with status 'invited') to 'joined' or 'rejected'.
        Handles transaction and conversation timestamp updates.
        """
        participant = await self.part_repo.get_participant_by_id(participant_id)
        if not participant:
            raise ParticipantNotFoundError(
                f"Participant record '{participant_id}' not found."
            )

        if participant.user_id != current_user.id:
            raise NotAuthorizedError("Cannot modify another user's participant record.")

        if participant.status != ParticipantStatus.INVITED:
            raise BusinessRuleError(
                f"Cannot update status from '{participant.status.value}'. Expected 'invited'."
            )

        if target_status not in [ParticipantStatus.JOINED, ParticipantStatus.REJECTED]:
            raise BusinessRuleError(
                f"Invalid target status '{target_status.value}'. Must be 'joined' or 'rejected'."
            )

        try:
            updated_participant = await self.part_repo.update_participant_status(
                participant=participant,
                new_status=target_status,
                expected_current_status=ParticipantStatus.INVITED,
            )

            if target_status == ParticipantStatus.JOINED:
                conversation = await self.conv_repo.get_conversation_by_id(
                    participant.conversation_id
                )
                if not conversation:
                    logger.error(
                        f"Data integrity issue: Conversation {participant.conversation_id} not found "
                        f"for participant {participant.id} during status update."
                    )
                    raise DatabaseError("Associated conversation data not found.")

                await self.conv_repo.update_conversation_activity(conversation)

            await self.session.commit()

            await self.session.refresh(updated_participant)

        except ValueError as e:
            await self.session.rollback()
            logger.warning(
                f"Status update precondition failed for participant {participant_id}: {e}"
            )
            raise BusinessRuleError(str(e))
        except IntegrityError as e:
            await self.session.rollback()
            logger.warning(
                f"Integrity error updating participant {participant_id}: {e}",
                exc_info=True,
            )
            raise ConflictError("Could not update participant due to a data conflict.")
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(
                f"Database error updating participant {participant_id}: {e}",
                exc_info=True,
            )
            raise DatabaseError("Failed to update participant due to a database error.")
        except Exception as e:
            await self.session.rollback()
            logger.error(
                f"Unexpected error updating participant {participant_id}: {e}",
                exc_info=True,
            )
            raise ServiceError(
                "An unexpected error occurred during participant update."
            )

        return updated_participant
