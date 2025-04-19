from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID  # Import UUID

# Remove unused SQLAlchemy imports
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload

# Updated db dependency import -> No longer needed
# from app.db import get_db_session
from app.models import User  # Keep User for type hint
from app.schemas.participant import (
    ParticipantUpdateRequest,
    ParticipantResponse,
    ParticipantStatus,  # Import the Enum
)  # Import schemas
from app.users import current_active_user  # Import dependency

# Remove unused datetime
# from datetime import datetime, timezone

# Import repositories
from app.repositories.dependencies import (
    get_user_repository,
    get_participant_repository,
    get_conversation_repository,
)
from app.repositories.user_repository import UserRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.conversation_repository import ConversationRepository


router = APIRouter(prefix="/participants", tags=["participants"])


@router.put("/{participant_id}", response_model=ParticipantResponse)
async def update_participant_status(
    # participant_id: str,
    participant_id: UUID,  # Change type hint to UUID
    update_data: ParticipantUpdateRequest,
    # Inject repositories
    user_repo: UserRepository = Depends(get_user_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    user: User = Depends(current_active_user),  # Get authenticated user
    # db: AsyncSession = Depends(get_db_session), # Remove direct session
):
    """Updates the status of a participant record (e.g., accept/reject invitation)."""

    # --- Placeholder Auth ---
    # TODO: Replace with actual authenticated user dependency
    # current_user = await user_repo.get_user_by_username("test-user-me") # REMOVED
    current_user = user  # Use authenticated user
    # if not current_user:
    #     raise HTTPException(status_code=403, detail="User not found (placeholder)") # Handled by Depends
    # --- End Placeholder ---

    # --- Fetch Participant --- Use repository
    # participant_id is now a UUID object thanks to FastAPI
    participant = await part_repo.get_participant_by_id(participant_id)

    if not participant:
        raise HTTPException(status_code=404, detail="Participant record not found")

    # --- Authorization Check --- Ensure current user owns this participant record
    if participant.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's participant record"
        )

    # --- Validate Target Status --- (State machine logic moved to repo/service layer ideally)
    try:
        target_status_enum = ParticipantStatus(update_data.status)
        if target_status_enum not in [
            ParticipantStatus.JOINED,
            ParticipantStatus.REJECTED,
        ]:
            raise ValueError  # Raise ValueError to be caught below
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target status '{update_data.status}'",
        )

    # --- Update Participant & Conversation (using Repositories) ---
    try:
        # Update participant status, ensuring current status is 'invited'
        updated_participant = await part_repo.update_participant_status(
            participant=participant,
            new_status=target_status_enum,
            expected_current_status=ParticipantStatus.INVITED,
        )

        # Update conversation timestamp if joining
        if target_status_enum == ParticipantStatus.JOINED:
            # Need to fetch conversation if not loaded, or ensure it's loaded
            # For simplicity, fetch it again here if needed.
            # A better approach might load it with the participant initially.
            conversation = await conv_repo.get_conversation_by_id(
                participant.conversation_id
            )
            if conversation:
                await conv_repo.update_conversation_activity(conversation)
            else:
                # This state indicates a data integrity issue (participant exists w/o conversation)
                print(
                    f"Error: Conversation {participant.conversation_id} not found for participant {participant.id}"
                )
                raise HTTPException(
                    status_code=500,
                    detail="Internal server error: Conversation data missing",
                )

        # Commit transaction
        await part_repo.session.commit()  # Commit via any repo using the same session

    except ValueError as e:
        # Raised by update_participant_status if current status wasn't 'invited'
        await part_repo.session.rollback()
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
    except Exception as e:
        # Catch-all for other potential DB errors
        await part_repo.session.rollback()
        # TODO: Log e
        print(f"Error updating participant {participant_id}: {e}")  # Temp print
        raise HTTPException(
            status_code=500, detail="Database error updating participant."
        )
    # -------------------------------------------------------

    return updated_participant
