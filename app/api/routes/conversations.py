import logging

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse

from app.api.common import APIResponse, BaseRouter
from app.auth_config import current_active_user
from app.logic.conversation_processing import (
    handle_create_conversation,
    handle_create_message,
    handle_get_conversation,
    handle_get_new_conversation_form,
    handle_invite_participant,
    handle_list_conversations,
)
from app.models import User
from app.repositories.dependencies import get_user_repository
from app.repositories.user_repository import UserRepository
from app.schemas.participant import ParticipantInviteRequest, ParticipantResponse
from app.services.conversation_service import ConversationService
from app.services.dependencies import get_conversation_service

logger = logging.getLogger(__name__)
conversations_router_instance = APIRouter()
router = BaseRouter(router=conversations_router_instance)


@router.get("/conversations", tags=["conversations"])
async def list_conversations(
    request: Request,
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Provides an HTML page listing all public conversations by calling the handler."""
    conversations = await handle_list_conversations(conv_service=conv_service)
    return APIResponse.html_response(
        template_name="conversations/list.html",
        context={"conversations": conversations},
        request=request,
    )


@router.get(
    "/conversations/new",
    name="get_new_conversation_form",
    tags=["conversations"],
)
async def get_new_conversation_form(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the form to create a new conversation by calling the handler."""
    context = await handle_get_new_conversation_form(request=request)
    return APIResponse.html_response(
        template_name="conversations/new.html", context=context, request=request
    )


@router.get(
    "/conversations/{slug}",
    tags=["conversations"],
)
async def get_conversation(
    slug: str,
    request: Request,
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Retrieves and displays a specific conversation by calling the handler."""
    conversation = await handle_get_conversation(
        slug=slug, requesting_user=user, conv_service=conv_service
    )

    return APIResponse.html_response(
        template_name="conversations/detail.html",
        context={
            "conversation": conversation,
            "participants": conversation.participants if conversation else [],
            "messages": conversation.messages if conversation else [],
        },
        request=request,
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
    """Handles the form submission by calling the processing logic."""
    logger.info(f"Creating conversation with invitee: {invitee_username}")
    conversation = await handle_create_conversation(
        invitee_username=invitee_username,
        initial_message=initial_message,
        creator_user=user,
        conv_service=conv_service,
        user_repo=user_repo,
    )

    logger.info(f"Conversation created: {conversation}")

    redirect_url = f"/conversations/{conversation.slug}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


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
    new_participant = await handle_invite_participant(
        conversation_slug=slug,
        invitee_user_id_str=request_data.invitee_user_id,
        inviter_user=user,
        conv_service=conv_service,
    )
    return new_participant


@router.post(
    "/conversations/{slug}/messages",
    status_code=status.HTTP_303_SEE_OTHER,
    name="create_message",
    tags=["conversations", "messages"],
)
async def create_message(
    slug: str,
    message_content: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Handles creating a new message in a conversation."""
    await handle_create_message(
        conversation_slug=slug,
        message_content=message_content,
        sender_user=user,
        conv_service=conv_service,
    )
    redirect_url = f"/conversations/{slug}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
