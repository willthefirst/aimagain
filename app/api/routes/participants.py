from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Updated db dependency import
from app.db import get_db_session
from app.models import Participant, User, Conversation  # Import models
from app.schemas.participant import (
    ParticipantUpdateRequest,
    ParticipantResponse,
)  # Import schemas
from datetime import datetime, timezone  # Added timezone

router = APIRouter(prefix="/participants", tags=["participants"])


@router.put(
    "/{participant_id}", response_model=ParticipantResponse  # Use response schema
)
async def update_participant_status(  # Make async
    participant_id: str,
    update_data: ParticipantUpdateRequest,
    db: AsyncSession = Depends(get_db_session),  # Use get_db_session
):
    """Updates the status of a participant record (e.g., accept/reject invitation)."""

    # --- Placeholder Auth ---
    # TODO: Replace with actual authenticated user
    current_user_stmt = select(User).filter(
        User.username == "test-user-me"
    )  # Use select
    current_user_result = await db.execute(current_user_stmt)  # Use await db.execute
    current_user = current_user_result.scalars().first()
    if not current_user:
        raise HTTPException(status_code=403, detail="User not found (placeholder)")
    # --- End Placeholder ---

    # --- Fetch Participant --- Use select
    participant_stmt = (
        select(Participant)
        .filter(Participant.id == participant_id)
        .options(
            selectinload(Participant.conversation)
        )  # Load conversation for timestamp update
    )
    participant_result = await db.execute(participant_stmt)  # Use await db.execute
    participant = participant_result.scalars().first()

    if not participant:
        raise HTTPException(status_code=404, detail="Participant record not found")

    # --- Authorization Check --- Ensure current user owns this participant record
    if participant.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Cannot modify another user's participant record"
        )

    # --- State Machine Logic ---
    # Can only change status if current status is 'invited'
    if participant.status != "invited":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from '{participant.status}'",
        )

    # Target status must be 'joined' or 'rejected'
    if update_data.status not in ["joined", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target status '{update_data.status}'",
        )

    # --- Update Participant --- Apply the new status
    participant.status = update_data.status
    now = datetime.now(timezone.utc)
    participant.updated_at = now
    if update_data.status == "joined":
        participant.joined_at = now

    db.add(participant)

    # --- Update Conversation Timestamp (if joining) ---
    if update_data.status == "joined":
        conversation = participant.conversation
        if conversation:
            conversation.last_activity_at = now
            conversation.updated_at = now
            db.add(conversation)
        else:
            # This case should ideally not happen if FK constraints are set
            await db.rollback()
            raise HTTPException(
                status_code=500, detail="Conversation not found for participant"
            )

    # --- Commit and Return --- Async commit and refresh
    try:
        await db.commit()
        await db.refresh(participant)
        if update_data.status == "joined" and conversation:
            await db.refresh(conversation)
    except Exception as e:
        await db.rollback()
        # Log e
        raise HTTPException(
            status_code=500, detail="Database error updating participant."
        )

    return participant
