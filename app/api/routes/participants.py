from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
import logging

# Remove unused imports
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload
# from app.db import get_db_session
# from app.repositories.dependencies import (
#     get_user_repository,
#     get_participant_repository,
#     get_conversation_repository,
# )
# from app.repositories.user_repository import UserRepository
# from app.repositories.participant_repository import ParticipantRepository
# from app.repositories.conversation_repository import ConversationRepository

from app.models import User
from app.schemas.participant import (
    ParticipantUpdateRequest,
    ParticipantResponse,
    ParticipantStatus,
)
from app.auth_config import current_active_user

# Import ParticipantService dependency
from app.services.dependencies import get_participant_service
from app.services.participant_service import (
    ParticipantService,
    ParticipantNotFoundError,
    # Import relevant exceptions (might need to move to shared location)
    ServiceError,
    NotAuthorizedError,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
)

# Import the new handler
from app.logic.participant_processing import handle_update_participant_status

# Import shared error handling function
from app.api.errors import handle_service_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/participants", tags=["participants"])


@router.put("/{participant_id}", response_model=ParticipantResponse)
async def update_participant_status(
    participant_id: UUID,
    update_data: ParticipantUpdateRequest,
    user: User = Depends(current_active_user),
    # Depend on the service
    part_service: ParticipantService = Depends(get_participant_service),
):
    """Updates the status of the user's participant record (e.g., accept/reject invitation)."""

    try:
        # Validate target status from request data
        try:
            target_status_enum = ParticipantStatus(update_data.status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target status value '{update_data.status}'. Must be 'joined' or 'rejected'.",
            )

        # Delegate logic to the handler
        updated_participant = await handle_update_participant_status(
            participant_id=participant_id,
            target_status=target_status_enum,
            current_user=user,
            part_service=part_service,
        )

        return updated_participant

    # Handle specific service errors using the helper
    except (
        ParticipantNotFoundError,
        NotAuthorizedError,
        BusinessRuleError,
        ConflictError,
        DatabaseError,
    ) as e:
        handle_service_error(e)
    except ServiceError as e:  # Catch-all for other service errors
        handle_service_error(e)
    except Exception as e:
        # Catch unexpected errors
        logger.error(
            f"Unexpected error updating participant {participant_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )
