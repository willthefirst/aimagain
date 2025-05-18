import logging
from uuid import UUID

from app.models import User
from app.schemas.participant import ParticipantStatus
from app.services.participant_service import (
    BusinessRuleError,
    ConflictError,
    DatabaseError,
    NotAuthorizedError,
    ParticipantNotFoundError,
    ParticipantService,
    ServiceError,
)

logger = logging.getLogger(__name__)


async def handle_update_participant_status(
    participant_id: UUID,
    target_status: ParticipantStatus,
    current_user: User,
    part_service: ParticipantService,
):
    """
    Handles the core logic for updating a participant's invitation status.

    Args:
        participant_id: The ID of the participant record to update.
        target_status: The new status for the participant.
        current_user: The user making the request.
        part_service: The participant service dependency.

    Returns:
        The updated participant record.

    Raises:
        ParticipantNotFoundError: If the participant is not found.
        NotAuthorizedError: If the user is not authorized to perform the update.
        BusinessRuleError: If a business rule is violated (e.g., invalid status transition).
        ConflictError: If there's a conflict during the update.
        DatabaseError: If a database error occurs.
        ServiceError: For other generic service-level errors.
    """
    logger.debug(
        f"Handler: Updating participant {participant_id} to status {target_status} by user {current_user.id}"
    )
    try:
        updated_participant = await part_service.update_invitation_status(
            participant_id=participant_id,
            target_status=target_status,
            current_user=current_user,
        )
        logger.info(
            f"Handler: Participant {participant_id} status updated successfully."
        )
        return updated_participant
    except (
        ParticipantNotFoundError,
        NotAuthorizedError,
        BusinessRuleError,
        ConflictError,
        DatabaseError,
        ServiceError,
    ) as e:
        logger.info(
            f"Handler: Service error updating participant {participant_id}: {e}"
        )
        raise  # Re-raise for the route to handle
    except Exception as e:
        logger.error(
            f"Handler: Unexpected error updating participant {participant_id}: {e}",
            exc_info=True,
        )
        raise ServiceError(
            f"An unexpected error occurred while updating participant {participant_id}."
        )
