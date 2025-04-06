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