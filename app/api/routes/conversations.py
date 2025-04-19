from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from uuid import UUID  # Import UUID

# Use AsyncSession for async operations
# Remove direct AsyncSession import if no longer needed directly in routes
from sqlalchemy.ext.asyncio import AsyncSession  # Temporarily re-import

# from sqlalchemy.orm import joinedload, selectinload # Keep if needed for other routes

# Import select for modern query style
from sqlalchemy import select  # Keep if needed for other routes

from app.core.templating import templates

# Remove direct db session dependency
from app.db import get_db_session  # Add back for unrefactored routes
from app.repositories.dependencies import (
    get_conversation_repository,
    get_user_repository,
    get_participant_repository,
)  # Import repository dependency
from app.repositories.conversation_repository import (
    ConversationRepository,
)  # Import repository type
from app.repositories.user_repository import UserRepository
from app.repositories.participant_repository import ParticipantRepository

# Import ORM models (keep as needed for type hints or other routes)
from app.models import Conversation, Participant, User, Message  # Add Message

# Import schemas (keep as needed)
from app.schemas.conversation import ConversationCreateRequest, ConversationResponse
from app.schemas.participant import (
    ParticipantInviteRequest,
    ParticipantResponse,
)  # Import schemas
import uuid  # For slug generation
from datetime import datetime, timezone  # For timestamps

router = APIRouter()


@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
async def list_conversations(
    request: Request,
    # Inject the repository instead of the session
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
):  # Use get_db_session
    """Provides an HTML page listing all public conversations using ORM."""

    # Use the repository method
    conversations = await conv_repo.list_conversations()

    # Pass the raw ORM objects directly to the template
    return templates.TemplateResponse(
        name="conversations/list.html",
        context={
            "request": request,
            "conversations": conversations,
        },  # Pass ORM objects
    )


@router.get(
    "/conversations/{slug}",
    # response_model=..., # Add later
    response_class=HTMLResponse,  # Assuming HTML response for now
    tags=["conversations"],
)
async def get_conversation(  # Async function
    slug: str,
    request: Request,  # Keep request for template context
    # Inject the repository
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    # Inject user and participant repos for auth check
    user_repo: UserRepository = Depends(get_user_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    # TODO: Replace placeholder auth with actual user dependency
):
    """Retrieves details for a specific conversation."""
    print(
        f"--- [Route get_conversation] Finding conversation slug: {slug} ---"
    )  # Added print
    # Use repository method to get the conversation by slug
    conversation = await conv_repo.get_conversation_by_slug(slug)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )

    # --- Authorization Check (Refactored to use repositories) ---
    # TODO: Replace placeholder with actual authenticated user dependency
    print(
        f"--- [Route get_conversation] Attempting to find user 'test-user-me' for auth check ---"
    )  # Added print
    current_user = await user_repo.get_user_by_username("test-user-me")  # Use repo
    print(
        f"--- [Route get_conversation] Found user for auth check: {current_user.username if current_user else 'None'} ---"
    )  # Added print
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Check participation using participant repository
    participant = await part_repo.get_participant_by_user_and_conversation(
        user_id=current_user.id, conversation_id=conversation.id
    )

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a participant in this conversation",
        )

    if participant.status != "joined":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has not joined this conversation",
        )
    # --------------------------

    # Authorization passed, user is joined.
    # Fetch full conversation data using the repository method
    conversation_details = await conv_repo.get_conversation_details(conversation.id)

    # If details couldn't be fetched (e.g., concurrent delete), handle it
    if not conversation_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation details not found",
        )

    # Sort messages by creation date (ascending) in Python
    sorted_messages = sorted(
        conversation_details.messages, key=lambda msg: msg.created_at
    )

    return templates.TemplateResponse(
        "conversations/detail.html",
        {
            "request": request,
            "conversation": conversation_details,
            "participants": conversation_details.participants,  # Pass participants separately if needed by template
            "messages": sorted_messages,
        },
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,  # Use the response schema
    status_code=status.HTTP_201_CREATED,  # Set default success status code
    tags=["conversations"],
)
async def create_conversation(  # Async function
    request_data: ConversationCreateRequest,  # Use the request schema
    # Inject repositories
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    # TODO: Replace placeholder auth with actual user dependency
):
    """Creates a new conversation by inviting another user."""
    print(
        f"--- [Route create_conversation] Attempting to find creator 'test-user-me' ---"
    )  # Added print
    # --- User Checks (Refactored) ---
    # 1. Get creator (placeholder)
    # TODO: Replace with actual authenticated user dependency
    creator_user = await user_repo.get_user_by_username("test-user-me")  # Use repo
    print(
        f"--- [Route create_conversation] Found creator: {creator_user.username if creator_user else 'None'} ---"
    )  # Added print
    if not creator_user:
        raise HTTPException(status_code=403, detail="Auth user not found - placeholder")

    # 2. Find invitee and check if online
    try:
        invitee_user_id_uuid = UUID(request_data.invitee_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invitee user ID format")

    invitee_user = await user_repo.get_user_by_id(
        # request_data.invitee_user_id
        invitee_user_id_uuid  # Pass UUID object
    )  # Use repo
    if not invitee_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitee user not found"
        )
    if not invitee_user.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invitee user is not online"
        )
    # --------------------------------

    # --- Create Conversation via Repository ---
    try:
        # Use the repository method to create conversation, message, and participants
        new_conversation = await conv_repo.create_new_conversation(
            creator_user=creator_user,
            invitee_user=invitee_user,
            initial_message_content=request_data.initial_message,
        )
        # Commit is handled outside the repository method (here, at end of request)
        await conv_repo.session.commit()
    except Exception as e:
        await conv_repo.session.rollback()  # Rollback on the session used by the repo
        # TODO: Log the error e
        print(f"Error creating conversation: {e}")  # Temporary print
        raise HTTPException(
            status_code=500, detail="Database error during conversation creation."
        )
    # ----------------------------------------

    # Return the created conversation (Pydantic converts ORM object)
    return new_conversation


@router.post(
    "/conversations/{slug}/participants",
    response_model=ParticipantResponse,  # Use ParticipantResponse
    status_code=status.HTTP_201_CREATED,
    tags=["conversations", "participants"],
)
async def invite_participant(  # Async function
    slug: str,
    request_data: ParticipantInviteRequest,  # Use request schema
    # Inject repositories
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    # TODO: Replace placeholder auth with actual user dependency
):
    """Invites another user to an existing conversation."""
    print(
        f"--- [Route invite_participant] Finding conversation slug: {slug} ---"
    )  # Added print
    # --- Get Conversation (Refactored) ---
    conversation = await conv_repo.get_conversation_by_slug(slug)
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )

    # --- Authorize Requesting User (Refactored) ---
    # TODO: Replace placeholder with actual authenticated user dependency
    current_user = await user_repo.get_user_by_username("test-user-me")  # Use repo
    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Check if current user is joined using participant repository
    is_joined = await part_repo.check_if_user_is_joined_participant(
        user_id=current_user.id, conversation_id=conversation.id
    )
    if not is_joined:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User must be a joined participant to invite others",
        )
    # -----------------------------------------

    # --- Validate Invitee (Refactored) ---
    try:
        invitee_user_id_uuid = UUID(request_data.invitee_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid invitee user ID format")

    invitee_user = await user_repo.get_user_by_id(
        # request_data.invitee_user_id
        invitee_user_id_uuid  # Pass UUID object
    )  # Use repo
    if not invitee_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitee user not found"
        )

    if not invitee_user.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invitee user is not online"
        )

    # Check if invitee is already a participant using participant repository
    existing_invitee_participant = (
        await part_repo.get_participant_by_user_and_conversation(
            user_id=invitee_user.id, conversation_id=conversation.id
        )
    )
    if existing_invitee_participant:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitee is already a participant",
        )
    # ----------------------------------

    # --- Create Participant and Update Conversation (Refactored) ---
    try:
        # Create participant record using participant repository
        new_participant = await part_repo.create_participant(
            user_id=invitee_user.id,
            conversation_id=conversation.id,
            status="invited",
            invited_by_user_id=current_user.id,
            # No initial message for invites to existing conversations
        )

        # Update conversation timestamps using conversation repository
        await conv_repo.update_conversation_timestamps(conversation)

        # Commit changes
        # Note: Committing the session used by one repo commits changes made via other repos
        # using the same session instance (which they do via Depends(get_db_session)).
        await part_repo.session.commit()  # Can commit using any repo's session

        # Refresh the new participant to ensure all fields are loaded
        # (refresh is done within create_participant and update_conversation_timestamps methods)

    except Exception as e:
        await part_repo.session.rollback()  # Rollback using any repo's session
        # TODO: Log e
        print(f"Error inviting participant: {e}")  # Temporary print
        raise HTTPException(
            status_code=500, detail="Database error inviting participant."
        )
    # -------------------------------------------------------------

    return new_participant
