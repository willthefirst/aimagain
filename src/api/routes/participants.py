import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form

from src.api.common import BadRequestError, BaseRouter
from src.auth_config import current_active_user
from src.logic.participant_processing import handle_update_participant_status
from src.models import User
from src.schemas.participant import ParticipantResponse, ParticipantStatus
from src.services.dependencies import get_participant_service
from src.services.participant_service import ParticipantService

logger = logging.getLogger(__name__)
participants_router_instance = APIRouter(prefix="/participants")
router = BaseRouter(router=participants_router_instance, default_tags=["participants"])


@router.put("/{participant_id}", response_model=ParticipantResponse)
async def update_participant_status(
    participant_id: UUID,
    status: str = Form(...),
    user: User = Depends(current_active_user),
    part_service: ParticipantService = Depends(get_participant_service),
):
    """Updates the status of the user's participant record (e.g., accept/reject invitation).

    This endpoint allows a user to update their participation status for a conversation,
    typically to accept or reject an invitation.

    Args:
        participant_id: The UUID of the participant record to update.
        status: The new status as a form field.
        user: The currently authenticated user, who must own the participant record.
        part_service: The participant service for handling business logic.

    Returns:
        ParticipantResponse: The updated participant record.

    Raises:
        BadRequestError: If the `status` value is not a valid `ParticipantStatus` enum member.
                         Other service-level errors are handled by the BaseRouter's error handling decorator.
    """

    try:
        target_status_enum = ParticipantStatus(status)
    except ValueError:
        raise BadRequestError(
            detail=f"Invalid target status value '{status}'. Must be 'joined' or 'rejected'."
        )

    updated_participant = await handle_update_participant_status(
        participant_id=participant_id,
        target_status=target_status_enum,
        current_user=user,
        part_service=part_service,
    )

    return updated_participant
