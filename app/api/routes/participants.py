from fastapi import APIRouter, Depends, HTTPException

# Import async session and select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from datetime import datetime, timezone

from app.db import get_db
from app.models import Participant, User, Conversation  # Import models
from app.schemas.participant import (
    ParticipantUpdateRequest,
    ParticipantResponse,
)  # Import schemas

router = APIRouter(prefix="/participants", tags=["participants"])


@router.put(
    "/{participant_id}", response_model=ParticipantResponse  # Use response schema
)
async def update_participant_status(  # Make async
    participant_id: str,
    update_data: ParticipantUpdateRequest,
    db: AsyncSession = Depends(get_db),  # Use AsyncSession
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
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")
    # --- End Placeholder ---

    # Fetch the participant record, ensuring it belongs to the current user
    participant_stmt = (
        select(Participant).where(Participant.id == participant_id)
        # .options(joinedload(Participant.conversation)) # Optional: Load conversation if needed later
    )
    participant_result = await db.execute(participant_stmt)  # Use await db.execute
    participant = participant_result.scalars().first()

    if not participant:
        raise HTTPException(status_code=404, detail="Participant record not found")

    # Verify the participant record belongs to the authenticated user
    if participant.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Cannot modify participant record for another user"
        )

    # Validate the requested status change
    # Currently, only allow updates from 'invited' to 'joined' or 'rejected'
    if participant.status != "invited":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from '{participant.status}', must be 'invited'",
        )

    if update_data.status not in ["joined", "rejected"]:
        # This check might be redundant if the Pydantic model uses an Enum
        raise HTTPException(
            status_code=422,
            detail=f"Invalid target status '{update_data.status}'. Must be 'joined' or 'rejected'.",
        )

    # Update the participant status
    participant.status = update_data.status
    if update_data.status == "joined":
        # Optionally set joined_at timestamp, etc.
        # participant.joined_at = datetime.now(timezone.utc)
        pass

    # Use update statement for efficiency (optional, direct assignment works too)
    # update_stmt = (
    #     update(Participant)
    #     .where(Participant.id == participant_id)
    #     .values(status=update_data.status)
    # )
    # await db.execute(update_stmt)

    db.add(participant)  # Add the modified object back to the session
    await db.commit()  # Commit the change
    await db.refresh(participant)  # Refresh to get latest state if needed

    return participant  # Return the updated participant (Pydantic model handles serialization)

    # Update conversation last_activity_at
    # Eager load conversation if not already loaded (though it might be via session)
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == participant.conversation_id)
        .first()
    )
    if conversation:
        conversation.last_activity_at = now
        conversation.updated_at = now  # Also update conversation itself
        db.add(conversation)

    try:
        db.commit()
        db.refresh(participant)
        if conversation:
            db.refresh(conversation)
    except Exception as e:
        db.rollback()
        # Log e
        raise HTTPException(
            status_code=500, detail="Database error updating participant status."
        )
