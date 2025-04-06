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

    # Use ORM query with relationship loading to avoid N+1
    # - selectinload fetches participants for each conversation in a separate query
    # - joinedload fetches the user for each participant in the second query
    conversations = (
        db.query(Conversation)
        .options(
            selectinload(Conversation.participants)
            .joinedload(Participant.user)
        )
        # Add ordering later, e.g., .order_by(Conversation.last_activity_at.desc())
        .all()
    )

    # Format data for the template directly from ORM objects
    conversation_summaries = []
    for convo in conversations:
        # Filter participants in Python - usually efficient enough for moderate numbers
        joined_usernames = [
            p.user.username for p in convo.participants if p.status == 'joined' and p.user
        ]
        conversation_summaries.append({
            "slug": convo.slug,
            "name": convo.name,
            "last_activity_at": convo.last_activity_at,
            "participants": joined_usernames
        })

    return templates.TemplateResponse(
        name="conversations/list.html",
        context={"request": request, "conversations": conversation_summaries}
    ) 