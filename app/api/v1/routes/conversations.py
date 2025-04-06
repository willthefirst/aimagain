from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
# Import Session for type hinting and ORM features
from sqlalchemy.orm import Session, joinedload, selectinload
# Removed unused Connection, select, join, and_

from app.core.templating import templates
from app.db import get_db
# Import ORM models
from app.models import Conversation, Participant, User # Keep all

router = APIRouter()

@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
def list_conversations(request: Request, db: Session = Depends(get_db)): # Depend on Session
    """Provides an HTML page listing all public conversations using ORM."""

    # Query conversations with eager loading of participants and their users
    conversations = (
        db.query(Conversation)
        .options(
            selectinload(Conversation.participants)
            .joinedload(Participant.user)
        )
        # Order by last activity, newest first (NULLs last)
        .order_by(Conversation.last_activity_at.desc().nullslast())
        .all()
    )

    # Pass the raw ORM objects to the template
    return templates.TemplateResponse(
        name="conversations/list.html",
        context={"request": request, "conversations": conversations}
    ) 