import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.decorators import handle_route_errors
from app.api.logging import log_route_call
from app.auth_config import current_active_user
from app.logic.participant_processing import handle_update_participant_status
from app.models import User
from app.schemas.participant import (
    ParticipantResponse,
    ParticipantStatus,
    ParticipantUpdateRequest,
)
from app.services.dependencies import get_participant_service
from app.services.participant_service import ParticipantService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/participants", tags=["participants"])


@router.put("/{participant_id}", response_model=ParticipantResponse)
@log_route_call
@handle_route_errors
async def update_participant_status(
    participant_id: UUID,
    update_data: ParticipantUpdateRequest,
    user: User = Depends(current_active_user),
    part_service: ParticipantService = Depends(get_participant_service),
):
    """Updates the status of the user's participant record (e.g., accept/reject invitation)."""

    try:
        target_status_enum = ParticipantStatus(update_data.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid target status value '{update_data.status}'. Must be 'joined' or 'rejected'.",
        )

    updated_participant = await handle_update_participant_status(
        participant_id=participant_id,
        target_status=target_status_enum,
        current_user=user,
        part_service=part_service,
    )

    return updated_participant
