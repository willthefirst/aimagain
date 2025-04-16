from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
# Use AsyncSession for async operations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
# Import select for modern query style
from sqlalchemy import select # Add select

from app.core.templating import templates
from app.db import get_db # Use async db dependency
# Import ORM models
from app.models import Conversation, Participant, User, Message # Add Message
# Import schemas
from app.schemas.conversation import ConversationCreateRequest, ConversationResponse
from app.schemas.participant import ParticipantInviteRequest, ParticipantResponse # Import schemas
import uuid # For slug generation
from datetime import datetime, timezone # For timestamps

router = APIRouter()

@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
async def list_conversations(request: Request, db: AsyncSession = Depends(get_db)): # Async function and AsyncSession
    """Provides an HTML page listing all public conversations using ORM."""

    # Use select() for async query construction
    stmt = (
        select(Conversation)
        .options(
            selectinload(Conversation.participants)
            .joinedload(Participant.user)
        )
        # Order by last activity, newest first (NULLs last)
        .order_by(Conversation.last_activity_at.desc().nullslast())
    )
    # Execute the query asynchronously and fetch all results
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    # Pass the raw ORM objects directly to the template
    return templates.TemplateResponse(
        name="conversations/list.html",
        context={"request": request, "conversations": conversations} # Pass ORM objects
    ) 

@router.get(
    "/conversations/{slug}",
    # response_model=..., # Add later
    response_class=HTMLResponse, # Assuming HTML response for now
    tags=["conversations"]
)
async def get_conversation( # Async function
    slug: str,
    request: Request, # Keep request for template context
    db: AsyncSession = Depends(get_db) # AsyncSession
    # TODO: Add auth dependency later
):
    """Retrieves details for a specific conversation."""
    # Async query for conversation
    stmt = select(Conversation).filter(Conversation.slug == slug)
    result = await db.execute(stmt)
    conversation = result.scalars().first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # --- Authorization Check ---
    # TODO: Replace placeholder with actual authenticated user
    # Async query for user
    user_stmt = select(User).filter(User.username == "test-user-me")
    user_result = await db.execute(user_stmt)
    current_user = user_result.scalars().first()
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Check if the current user is a participant in this conversation
    # Async query for participant
    participant_stmt = select(Participant).filter(
        Participant.conversation_id == conversation.id,
        Participant.user_id == current_user.id
    )
    participant_result = await db.execute(participant_stmt)
    participant = participant_result.scalars().first()

    if not participant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not a participant in this conversation")
    
    # Check participant status (must be 'joined' to view)
    if participant.status != 'joined':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User has not joined this conversation")
    # --------------------------

    # Authorization passed, user is joined.
    # Fetch full conversation data with participants/users and messages/senders
    # Using contains_eager helps load relationships based on the participant check we already did.
    # Load messages separately with ordering.
    # Async query for detailed conversation data
    details_stmt = (
        select(Conversation)
        .filter(Conversation.id == conversation.id)
        .options(
            selectinload(Conversation.participants).joinedload(Participant.user),
            selectinload(Conversation.messages).joinedload(Message.sender)
        )
    )
    details_result = await db.execute(details_stmt)
    # Use .one() appropriately if needed, or handle potential multiple results if structure allows
    # Using .first() might be safer unless you are absolutely sure one result exists
    conversation_details = details_result.scalars().one() # Use one() assuming ID is unique

    # Sort messages by creation date (ascending) in Python
    sorted_messages = sorted(
        conversation_details.messages,
        key=lambda msg: msg.created_at
    )

    return templates.TemplateResponse(
        "conversations/detail.html",
        {
            "request": request,
            "conversation": conversation_details,
            "participants": conversation_details.participants, # Pass participants separately if needed by template
            "messages": sorted_messages
        }
    )

@router.post(
    "/conversations",
    response_model=ConversationResponse, # Use the response schema
    status_code=status.HTTP_201_CREATED, # Set default success status code
    tags=["conversations"]
)
async def create_conversation( # Async function
    request_data: ConversationCreateRequest, # Use the request schema
    db: AsyncSession = Depends(get_db) # AsyncSession
    # TODO: Add dependency for authenticated user later
):
    """Creates a new conversation by inviting another user."""

    # --- TODO: Implement user checks later (Story 1 requirements) ---
    # 1. Get current authenticated user (replace with dependency)
    # Async query for creator user
    creator_stmt = select(User).limit(1) # Placeholder - MUST BE REPLACED WITH AUTH USER
    creator_result = await db.execute(creator_stmt)
    creator_user = creator_result.scalars().first()
    if not creator_user:
        raise HTTPException(status_code=403, detail="Auth user not found - placeholder")

    # 2. Find invitee and check if online
    # Async query for invitee user
    invitee_stmt = select(User).filter(User.id == request_data.invitee_user_id)
    invitee_result = await db.execute(invitee_stmt)
    invitee_user = invitee_result.scalars().first()
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
    await db.flush() # Flush to get the conversation ID

    # Create initial Message
    initial_message = Message(
        id=f"msg_{uuid.uuid4()}",
        content=request_data.initial_message,
        conversation_id=new_conversation.id,
        created_by_user_id=creator_user.id,
        created_at=now # Match conversation activity time
    )
    db.add(initial_message)
    await db.flush() # Flush to get the message ID

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
        await db.commit() # Async commit
        await db.refresh(new_conversation) # Async refresh
    except Exception as e:
        await db.rollback() # Async rollback
        # Log the error e
        raise HTTPException(status_code=500, detail="Database error during conversation creation.")

    # Return the created conversation data using the response schema
    # Pydantic will automatically convert the ORM object
    return new_conversation 

@router.post(
    "/conversations/{slug}/participants",
    response_model=ParticipantResponse, # Use ParticipantResponse
    status_code=status.HTTP_201_CREATED,
    tags=["conversations", "participants"]
)
async def invite_participant( # Async function
    slug: str,
    request_data: ParticipantInviteRequest, # Use request schema
    db: AsyncSession = Depends(get_db) # AsyncSession
    # TODO: Auth dependency
):
    """Invites another user to an existing conversation."""

    # --- Get Conversation ---
    # Async query for conversation
    conv_stmt = select(Conversation).filter(Conversation.slug == slug)
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalars().first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # --- Authorize Requesting User ---
    # TODO: Replace placeholder with actual authenticated user
    # Async query for current user
    user_stmt = select(User).filter(User.username == "test-user-me")
    user_result = await db.execute(user_stmt)
    current_user = user_result.scalars().first()
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Check if current user is already joined
    # Async query for current participant
    curr_part_stmt = select(Participant).filter(
        Participant.conversation_id == conversation.id,
        Participant.user_id == current_user.id,
        Participant.status == 'joined'
    )
    curr_part_result = await db.execute(curr_part_stmt)
    current_participant = curr_part_result.scalars().first()
    if not current_participant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User must be a joined participant to invite others")

    # --- Validate Invitee ---
    # Async query for invitee user
    invitee_stmt = select(User).filter(User.id == request_data.invitee_user_id)
    invitee_result = await db.execute(invitee_stmt)
    invitee_user = invitee_result.scalars().first()
    if not invitee_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitee user not found")

    # Check if invitee is online
    if not invitee_user.is_online:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invitee user is not online")

    # Check if invitee is already a participant
    # Async query for existing invitee participant
    exist_part_stmt = select(Participant).filter(
        Participant.conversation_id == conversation.id,
        Participant.user_id == invitee_user.id
    )
    exist_part_result = await db.execute(exist_part_stmt)
    existing_invitee_participant = exist_part_result.scalars().first()
    if existing_invitee_participant:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitee is already a participant")

    # --- Create New Participant Record ---
    now = datetime.now(timezone.utc)
    new_participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=invitee_user.id,
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=current_user.id,
        initial_message_id=None # No initial message for invites to existing convos
    )
    db.add(new_participant)

    # --- Update Conversation Timestamp ---
    conversation.last_activity_at = now
    conversation.updated_at = now
    db.add(conversation)

    # --- Commit and Return ---
    try:
        await db.commit() # Async commit
        await db.refresh(new_participant) # Async refresh
        await db.refresh(conversation) # Async refresh
    except Exception as e:
        await db.rollback() # Async rollback
        # Log e
        raise HTTPException(status_code=500, detail="Database error inviting participant.")

    return new_participant 