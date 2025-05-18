from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from uuid import UUID
import logging
from app.core.templating import templates
from app.auth_config import current_active_user
from app.repositories.user_repository import UserRepository
from app.repositories.dependencies import get_user_repository
from app.services.dependencies import get_conversation_service
from app.services.conversation_service import (
    ConversationService,
    ServiceError,
    ConversationNotFoundError,
    NotAuthorizedError,
    UserNotFoundError,
    BusinessRuleError,
    ConflictError,
    DatabaseError,
)
from app.models import Conversation, Participant, User, Message
from app.schemas.conversation import ConversationCreateRequest, ConversationResponse
from app.schemas.participant import ParticipantInviteRequest, ParticipantResponse
from app.api.errors import handle_service_error
from app.logic.conversation_processing import (
    handle_create_conversation,
    UserNotFoundError as LogicUserNotFoundError,
    handle_get_conversation,
    handle_list_conversations,
    handle_get_new_conversation_form,
    handle_invite_participant,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/conversations", response_class=HTMLResponse, tags=["conversations"])
async def list_conversations(
    request: Request,
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Provides an HTML page listing all public conversations by calling the handler."""
    try:
        conversations = await handle_list_conversations(conv_service=conv_service)
        return templates.TemplateResponse(
            name="conversations/list.html",
            context={
                "request": request,
                "conversations": conversations,
            },
        )
    except DatabaseError as e:
        logger.error(f"Database error in list_conversations route: {e}", exc_info=True)
        handle_service_error(e)
    except ServiceError as e:
        logger.error(f"Service error in list_conversations route: {e}", exc_info=True)
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error listing conversations route: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected server error occurred while trying to list conversations.",
        )


@router.get(
    "/conversations/new",
    response_class=HTMLResponse,
    name="get_new_conversation_form",
    tags=["conversations"],
)
async def get_new_conversation_form(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the form to create a new conversation by calling the handler."""
    try:
        context = await handle_get_new_conversation_form(request=request)
        return templates.TemplateResponse(
            name="conversations/new.html",
            context=context,
        )
    except ServiceError as e:
        logger.error(
            f"Service error in get_new_conversation_form route: {e}", exc_info=True
        )
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error in get_new_conversation_form route: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while preparing the new conversation form.",
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
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Retrieves and displays a specific conversation by calling the handler."""
    try:
        # Call the handler, passing dependencies explicitly
        conversation = await handle_get_conversation(
            slug=slug, requesting_user=user, conv_service=conv_service
        )

        # Log a Yolo message (as per original, if still desired)
        logger.info(
            f"Conversation details yolo: {conversation.id if conversation else 'None'}"
        )

        return templates.TemplateResponse(
            "conversations/detail.html",
            {
                "request": request,
                "conversation": conversation,
                # Ensure participants and messages are accessed safely if conversation can be None
                # However, ConversationNotFoundError should be caught below if no conversation
                "participants": conversation.participants if conversation else [],
                "messages": conversation.messages if conversation else [],
            },
        )
    # Handle specific service errors propagated from the handler
    except (ConversationNotFoundError, NotAuthorizedError) as e:
        # These errors are often translated to specific HTTP status codes
        # by handle_service_error (e.g., 404, 403)
        handle_service_error(e)
    except ServiceError as e:
        # Handle other generic service errors
        logger.error(
            f"Service error in get_conversation route for slug {slug}: {e}",
            exc_info=True,
        )
        handle_service_error(e)
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(
            f"Unexpected error in get_conversation route for slug {slug}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected server error occurred while retrieving conversation {slug}.",
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
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Invites another user to an existing conversation by calling the handler."""
    try:
        new_participant = await handle_invite_participant(
            conversation_slug=slug,
            invitee_user_id_str=request_data.invitee_user_id,  # Pass as string
            inviter_user=user,
            conv_service=conv_service,
        )
        return new_participant
    except BusinessRuleError as e:
        if "Invalid invitee user ID format" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid invitee user ID format.",
            )
        handle_service_error(e)
    except (
        ConversationNotFoundError,
        NotAuthorizedError,
        UserNotFoundError,
        ConflictError,
        DatabaseError,
    ) as e:
        handle_service_error(e)
    except ServiceError as e:
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error inviting participant to {slug} in route: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected server error occurred during the invitation process.",
        )
