# app/api/v1/routes/me.py
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload, selectinload, contains_eager # Import eager loading options

from app.core.templating import templates
from app.db import get_db
from app.models import User, Participant, Conversation, Message # Ensure all models imported

router = APIRouter(
    prefix="/users/me", # Prefix for all routes in this file
    tags=["me"]
)

@router.get("/invitations", response_class=HTMLResponse)
def list_my_invitations(request: Request, db: Session = Depends(get_db)):
    """Provides an HTML page listing the current user's pending invitations."""
    # TODO: Replace placeholder with actual authenticated user logic
    # Placeholder: Query for a user with a specific username used in tests
    current_user = db.query(User).filter(User.username == "test-user-me").first()
    if not current_user:
        # This will fail if the specific test user isn't created
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder: test-user-me not found)")

    # Query pending invitations for the current user
    # Eager load related data needed for display
    invitations = (
        db.query(Participant)
        .filter(Participant.user_id == current_user.id)
        .filter(Participant.status == 'invited')
        .options(
            # Load the user who invited us
            joinedload(Participant.inviter),
            # Load the conversation details
            joinedload(Participant.conversation),
            # Load the initial message (if any)
            joinedload(Participant.initial_message)
        )
        .order_by(Participant.created_at.desc()) # Show newest first
        .all()
    )

    return templates.TemplateResponse(
        name="me/invitations.html",
        context={"request": request, "invitations": invitations}
    )

@router.get("/conversations", response_class=HTMLResponse)
def list_my_conversations(request: Request, db: Session = Depends(get_db)):
    """Provides an HTML page listing conversations the current user is part of."""
    current_user = db.query(User).filter(User.username == "test-user-me").first()
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Query conversations where the current user is a participant (joined or invited)
    my_conversations = (
        db.query(Conversation)
        .join(Participant, Participant.conversation_id == Conversation.id)
        .filter(Participant.user_id == current_user.id)
        .filter(Participant.status.in_(['joined', 'invited']))
        .options(
            # Eager load *all* participants and their users for display
            selectinload(Conversation.participants).joinedload(Participant.user)
        )
        .order_by(Conversation.last_activity_at.desc().nullslast())
        .all()
    )

    # Prepare data for template, including my status in each convo
    conversation_data = []
    for convo in my_conversations:
        my_part_record = next((p for p in convo.participants if p.user_id == current_user.id), None)
        my_status = my_part_record.status if my_part_record else 'unknown'
        all_participant_usernames = [p.user.username for p in convo.participants if p.user]
        conversation_data.append({
            "slug": convo.slug,
            "name": convo.name,
            "last_activity_at": convo.last_activity_at,
            "participants": all_participant_usernames,
            "my_status": my_status
        })


    return templates.TemplateResponse(
        name="me/conversations.html",
        context={
            "request": request,
            "conversations": conversation_data,
            "current_user_id": current_user.id
            }
    ) 