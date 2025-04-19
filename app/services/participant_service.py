import uuid
import logging
from uuid import UUID
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.models import User, Participant, Conversation
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.participant import ParticipantStatus

# Import shared service exceptions
from .exceptions import (
    ServiceError,
    NotAuthorizedError,
    ConflictError,
    DatabaseError,
    BusinessRuleError,
    ParticipantNotFoundError,
    # Removed ConversationNotFoundError import as it's not explicitly raised here
    # Import UserNotFoundError if needed for future methods
)

logger = logging.getLogger(__name__)

# Removed local ParticipantNotFoundError definition
# class ParticipantNotFoundError(ServiceError):
#    ...


class ParticipantService:
    def __init__(
        self,
        participant_repository: ParticipantRepository,
        conversation_repository: ConversationRepository,
    ):
        self.part_repo = participant_repository
        self.conv_repo = conversation_repository
        self.session = participant_repository.session  # Share session

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

        # Authorization: Ensure the user owns this participant record
        if participant.user_id != current_user.id:
            raise NotAuthorizedError("Cannot modify another user's participant record.")

        # Business Rule: Can only transition from INVITED state via this method
        if participant.status != ParticipantStatus.INVITED:
            raise BusinessRuleError(
                f"Cannot update status from '{participant.status.value}'. Expected 'invited'."
            )

        # Business Rule: Target status must be JOINED or REJECTED
        if target_status not in [ParticipantStatus.JOINED, ParticipantStatus.REJECTED]:
            raise BusinessRuleError(
                f"Invalid target status '{target_status.value}'. Must be 'joined' or 'rejected'."
            )

        try:
            # Update participant status using repository method
            # The repo method should enforce the expected_current_status implicitly or explicitly
            updated_participant = await self.part_repo.update_participant_status(
                participant=participant,
                new_status=target_status,
                # Repository method might take expected_current_status, or we check above
                expected_current_status=ParticipantStatus.INVITED,
            )

            # If joining, update conversation activity timestamp
            if target_status == ParticipantStatus.JOINED:
                # Fetch the conversation - participant.conversation might not be loaded
                conversation = await self.conv_repo.get_conversation_by_id(
                    participant.conversation_id
                )
                if not conversation:
                    # This indicates a data integrity issue
                    logger.error(
                        f"Data integrity issue: Conversation {participant.conversation_id} not found "
                        f"for participant {participant.id} during status update."
                    )
                    # Raising DatabaseError as it's an internal data consistency problem
                    raise DatabaseError("Associated conversation data not found.")

                await self.conv_repo.update_conversation_activity(conversation)

            # Commit transaction
            await self.session.commit()

            # Refresh participant to get updated fields (like joined_at if set by DB)
            await self.session.refresh(updated_participant)
            # Optionally refresh conversation if its updated_at timestamp is needed
            # if 'conversation' in locals(): await self.session.refresh(conversation)

        except ValueError as e:
            # Catch potential error from repo if status precondition failed (if repo raises ValueError)
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
