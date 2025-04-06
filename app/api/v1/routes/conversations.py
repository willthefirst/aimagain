from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.engine import Connection
from sqlalchemy import select, join, and_ # Import join and and_

from app.core.templating import templates
from app.db import get_db
# Import all necessary models
from app.models import Conversation, Participant, User

router = APIRouter()

@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
def list_conversations(request: Request, db: Connection = Depends(get_db)):
    """Provides an HTML page listing all public conversations."""

    # 1. Query all conversations
    convo_query = select(Conversation) # Add ordering later if needed
    convo_result = db.execute(convo_query)
    conversations_raw = convo_result.fetchall()

    # 2. Prepare summaries, fetching joined participants for each
    conversation_summaries = []
    for convo in conversations_raw:
        # Query for joined participants and their usernames for this conversation
        participant_query = (
            select(User.c.username)
            .select_from(
                join(Participant, User, Participant.c.user_id == User.c._id)
            )
            .where(
                and_(
                    Participant.c.conversation_id == convo._id,
                    Participant.c.status == 'joined'
                )
            )
        )
        participant_result = db.execute(participant_query)
        # Fetch usernames as a list of strings
        joined_usernames = [row[0] for row in participant_result.fetchall()]

        conversation_summaries.append({
            "slug": convo.slug,
            "name": convo.name, # Include name if it exists
            "last_activity_at": convo.last_activity_at, # Include timestamp
            "participants": joined_usernames
        })

    return templates.TemplateResponse(
        name="conversations/list.html",
        context={"request": request, "conversations": conversation_summaries}
    ) 