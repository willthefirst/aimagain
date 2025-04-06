# app/api/v1/routes/participants.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.db import get_db
from app.models import Participant, User, Conversation # Import models
from app.schemas.participant import ParticipantUpdateRequest, ParticipantResponse # Import schemas

router = APIRouter(
    prefix="/participants",
    tags=["participants"]
)

@router.put(
    "/{participant_id}",
    response_model=ParticipantResponse # Use response schema
)
def update_participant_status(
    participant_id: str,
    update_data: ParticipantUpdateRequest,
    db: Session = Depends(get_db)
):
    """Updates the status of a participant record (e.g., accept/reject invitation)."""

    # --- Placeholder Auth ---
    # TODO: Replace with actual authenticated user
    current_user = db.query(User).filter(User.username == "test-user-me").first()
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")
    # --- End Placeholder ---

    # Find the participant record
    participant = db.query(Participant).filter(Participant.id == participant_id).first()

    if not participant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant record not found")

    # Authorization: Ensure the current user is the one this record belongs to
    if participant.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify another user's participation status")

    # Validate current status (can only accept/reject if currently 'invited')
    if participant.status != "invited":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot update status from '{participant.status}'")

    new_status = update_data.status
    if new_status not in ["joined", "rejected"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid target status. Must be 'joined' or 'rejected'")

    # Update status and potentially joined_at
    participant.status = new_status
    now = datetime.now(timezone.utc)
    participant.updated_at = now # Manually update timestamp (onupdate might not trigger on Session)
    if new_status == "joined":
        participant.joined_at = now

    # Update conversation last_activity_at
    # Eager load conversation if not already loaded (though it might be via session)
    conversation = db.query(Conversation).filter(Conversation.id == participant.conversation_id).first()
    if conversation:
        conversation.last_activity_at = now
        conversation.updated_at = now # Also update conversation itself
        db.add(conversation)

    db.add(participant)

    try:
        db.commit()
        db.refresh(participant)
        if conversation:
             db.refresh(conversation)
    except Exception as e:
        db.rollback()
        # Log e
        raise HTTPException(status_code=500, detail="Database error updating participant status.")

    return participant 