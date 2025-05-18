from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from uuid import UUID
import logging  # Use logging

# Removed unused SQLAlchemy imports
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select

from app.core.templating import templates
from app.auth_config import current_active_user

# Removed direct repository dependencies
# from app.repositories.dependencies import (
#     get_conversation_repository,
#     get_user_repository,
#     get_participant_repository,
# )
# from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.repositories.dependencies import get_user_repository

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
from app.logic.conversation_processing import (
    handle_create_conversation,
    UserNotFoundError as LogicUserNotFoundError,
    handle_get_conversation,
)


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
    "/conversations/new",
    response_class=HTMLResponse,
    name="get_new_conversation_form",
    tags=["conversations"],
)
async def get_new_conversation_form(
    request: Request,
    user: User = Depends(current_active_user),  # Requires auth
):
    """Displays the form to create a new conversation."""
    # TODO: Implement proper template rendering later
    # For now, return a placeholder or reference the template name
    return templates.TemplateResponse(
        name="conversations/new.html",  # Placeholder template name
        context={
            "request": request,
            # Add other context if needed later
        },
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
    conversation = await handle_get_conversation(slug, request, user, conv_service)

    logger.info(f"Conversation details yolo: {conversation}")

    return templates.TemplateResponse(
        "conversations/detail.html",
        {
            "request": request,
            "conversation": conversation,
            "participants": conversation.participants,
            "messages": conversation.messages,  # Assuming loaded and sorted
        },
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_303_SEE_OTHER,
    name="create_conversation",
    tags=["conversations"],
)
async def create_conversation(
    invitee_username: str = Form(...),
    initial_message: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
    user_repo: UserRepository = Depends(get_user_repository),
):
    logger.info(f"Creating conversation with invitee: {invitee_username}")
    """Handles the form submission by calling the processing logic."""
    try:
        # Call the decoupled logic handler
        conversation = await handle_create_conversation(
            invitee_username=invitee_username,
            initial_message=initial_message,
            creator_user=user,
            conv_service=conv_service,
            user_repo=user_repo,
        )

        logger.info(f"Conversation created: {conversation}")

        # Redirect on success
        redirect_url = f"/conversations/{conversation.slug}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    # --- Exception Translation --- #
    except LogicUserNotFoundError as e:
        # Translate logic layer UserNotFound to HTTP 404
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BusinessRuleError, ConflictError, DatabaseError) as e:
        # Translate specific service errors using existing handler
        # TODO: Improve error handling (e.g., flash messages on form)
        handle_service_error(e)
    except ServiceError as e:
        # Translate generic service errors
        # TODO: Improve error handling
        handle_service_error(e)
    # Removed catch for HTTPException as handler shouldn't raise it
    # except HTTPException as e:
    #     raise e
    except Exception as e:
        logger.error(
            f"Unexpected error in create_conversation route: {e}", exc_info=True
        )
        # TODO: Improve error handling
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
