from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
# Import Session for type hinting and ORM features
from sqlalchemy.orm import Session, joinedload, selectinload
# Removed unused Connection, select, join, and_

from app.core.templating import templates
from app.db import get_db
# Import ORM models
from app.models import Conversation, Participant, User, Message # Add Message
# Import schemas
from app.schemas.conversation import ConversationCreateRequest, ConversationResponse
import uuid # For slug generation
from datetime import datetime, timezone # For timestamps

router = APIRouter()

@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
def list_conversations(request: Request, db: Session = Depends(get_db)): # Depend on Session
    """Provides an HTML page listing all public conversations using ORM."""

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

    # Pass the raw ORM objects directly to the template
    return templates.TemplateResponse(
        name="conversations/list.html",
        context={"request": request, "conversations": conversations} # Pass ORM objects
    ) 

@router.post(
    "/conversations",
    response_model=ConversationResponse, # Use the response schema
    status_code=status.HTTP_201_CREATED, # Set default success status code
    tags=["conversations"]
)
def create_conversation(
    request_data: ConversationCreateRequest, # Use the request schema
    db: Session = Depends(get_db)
    # TODO: Add dependency for authenticated user later
):
    """Creates a new conversation by inviting another user."""

    # --- TODO: Implement user checks later (Story 1 requirements) ---
    # 1. Get current authenticated user (replace with dependency)
    creator_user = db.query(User).first() # Placeholder - MUST BE REPLACED WITH AUTH USER
    if not creator_user:
        raise HTTPException(status_code=403, detail="Auth user not found - placeholder")

    # 2. Find invitee and check if online
    invitee_user = db.query(User).filter(User.id == request_data.invitee_user_id).first()
    if not invitee_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitee user not found")
    if not invitee_user.is_online: # Check if invitee is online
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invitee user is not online")
    # ------------------------------------------------------------------

    # Generate a unique slug (simple version for now)
    slug = f"convo-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)

    # Create Conversation
    new_conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=slug,
        created_by_user_id=creator_user.id,
        last_activity_at=now # Initial activity
    )
    db.add(new_conversation)
    db.flush() # Flush to get the conversation ID

    # Create initial Message
    initial_message = Message(
        id=f"msg_{uuid.uuid4()}",
        content=request_data.initial_message,
        conversation_id=new_conversation.id,
        created_by_user_id=creator_user.id,
        created_at=now # Match conversation activity time
    )
    db.add(initial_message)
    db.flush() # Flush to get the message ID

    # Create Participant for creator
    creator_participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=creator_user.id,
        conversation_id=new_conversation.id,
        status="joined",
        joined_at=now
    )
    db.add(creator_participant)

    # Create Participant for invitee
    invitee_participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=request_data.invitee_user_id,
        conversation_id=new_conversation.id,
        status="invited",
        invited_by_user_id=creator_user.id,
        initial_message_id=initial_message.id # Link to the first message
    )
    db.add(invitee_participant)

    # Commit changes for this request
    # In a real app, consider moving commit logic outside the route
    # maybe using middleware or a different dependency pattern.
    try:
        db.commit()
        db.refresh(new_conversation) # Refresh to get updated fields like created_at
    except Exception as e:
        db.rollback()
        # Log the error e
        raise HTTPException(status_code=500, detail="Database error during conversation creation.")

    # Return the created conversation data using the response schema
    # Pydantic will automatically convert the ORM object
    return new_conversation 