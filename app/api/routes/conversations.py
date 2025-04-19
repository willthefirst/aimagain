from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from uuid import UUID
import logging  # Use logging

# Removed unused SQLAlchemy imports
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select

from app.core.templating import templates
from app.users import current_active_user

# Removed direct repository dependencies
# from app.repositories.dependencies import (
#     get_conversation_repository,
#     get_user_repository,
#     get_participant_repository,
# )
# from app.repositories.conversation_repository import ConversationRepository
# from app.repositories.user_repository import UserRepository
# from app.repositories.participant_repository import ParticipantRepository

# Import service dependency
from app.services.dependencies import get_conversation_service
from app.services.conversation_service import (
    ConversationService,
    ServiceError,  # Base exception
    ConversationNotFoundError,
    NotAuthorizedError,
    UserNotFoundError,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
)

# Import ORM models (needed for type hints)
from app.models import Conversation, Participant, User, Message

# Import schemas
from app.schemas.conversation import ConversationCreateRequest, ConversationResponse
from app.schemas.participant import ParticipantInviteRequest, ParticipantResponse

# Removed unused uuid and datetime imports if service handles them
# Import shared error handling function
from app.api.errors import handle_service_error


logger = logging.getLogger(__name__)  # Setup logger for route level

router = APIRouter()


@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
async def list_conversations(
    request: Request,
    # Depend on the service
    conv_service: ConversationService = Depends(get_conversation_service),
    # Require authentication to view conversations list?
    # user: User = Depends(current_active_user), # Add if needed
):
    """Provides an HTML page listing all public conversations."""
    try:
        conversations = await conv_service.get_conversations_for_listing()
        return templates.TemplateResponse(
            name="conversations/list.html",
            context={
                "request": request,
                "conversations": conversations,  # Pass ORM objects
            },
        )
    except DatabaseError as e:
        # Specific handling for database errors if needed, or use generic handler
        handle_service_error(e)
    except ServiceError as e:
        # Catch-all for other service errors (though should be minimal here)
        handle_service_error(e)
    except Exception as e:
        # Catch unexpected errors
        logger.error(f"Unexpected error listing conversations: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )


@router.get(
    "/conversations/{slug}",
    response_class=HTMLResponse,
    tags=["conversations"],
)
async def get_conversation(
    slug: str,
    request: Request,
    user: User = Depends(current_active_user),  # Requires auth
    # Depend on the service
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Retrieves details for a specific conversation if the user is authorized."""
    try:
        # Service method handles fetching and authorization
        conversation_details = await conv_service.get_conversation_details(
            slug=slug, requesting_user=user
        )

        # Service already sorted messages if implemented that way
        # sorted_messages = sorted(
        #     conversation_details.messages, key=lambda msg: msg.created_at
        # )

        return templates.TemplateResponse(
            "conversations/detail.html",
            {
                "request": request,
                "conversation": conversation_details,
                "participants": conversation_details.participants,  # Assuming loaded by service/repo
                "messages": conversation_details.messages,  # Assuming loaded and sorted
            },
        )
    # Handle specific service errors
    except (ConversationNotFoundError, NotAuthorizedError) as e:
        handle_service_error(e)
    except ServiceError as e:
        # Catch-all for other potential service errors
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error getting conversation {slug}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations"],
)
async def create_conversation(
    request_data: ConversationCreateRequest,
    user: User = Depends(current_active_user),  # Requires auth
    # Depend on the service
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Creates a new conversation by inviting another user."""
    try:
        # Validate UUID format early
        try:
            invitee_uuid = UUID(request_data.invitee_user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitee user ID format.",
            )

        # Delegate creation to the service
        new_conversation = await conv_service.create_new_conversation(
            creator_user=user,
            invitee_user_id=invitee_uuid,
            initial_message_content=request_data.initial_message,
        )

        # Return Pydantic model (FastAPI handles conversion from ORM object)
        return new_conversation

    # Handle specific service errors
    except (UserNotFoundError, BusinessRuleError, ConflictError, DatabaseError) as e:
        handle_service_error(e)
    except ServiceError as e:
        handle_service_error(e)
    except Exception as e:
        logger.error(f"Unexpected error creating conversation: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )


@router.post(
    "/conversations/{slug}/participants",
    response_model=ParticipantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations", "participants"],
)
async def invite_participant(
    slug: str,
    request_data: ParticipantInviteRequest,
    user: User = Depends(current_active_user),  # Requires auth
    # Depend on the service
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Invites another user to an existing conversation."""
    try:
        # Validate UUID format early
        try:
            invitee_uuid = UUID(request_data.invitee_user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitee user ID format.",
            )

        # Delegate invitation to the service
        new_participant = await conv_service.invite_user_to_conversation(
            conversation_slug=slug,
            invitee_user_id=invitee_uuid,
            inviter_user=user,
        )

        # Return Pydantic model
        return new_participant

    # Handle specific service errors
    except (
        ConversationNotFoundError,
        NotAuthorizedError,
        UserNotFoundError,
        BusinessRuleError,
        ConflictError,
        DatabaseError,
    ) as e:
        handle_service_error(e)
    except ServiceError as e:
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error inviting participant to {slug}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )


# Any other conversation-related routes would be refactored similarly
