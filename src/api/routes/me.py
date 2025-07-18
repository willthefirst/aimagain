import logging

from fastapi import APIRouter, Depends, Request

from src.api.common import APIResponse, BaseRouter
from src.auth_config import current_active_user
from src.logic.me_processing import (
    handle_get_my_conversations,
    handle_get_my_invitations,
)
from src.models import User
from src.services.dependencies import get_user_service
from src.services.user_service import UserService

logger = logging.getLogger(__name__)
me_router_instance = APIRouter(prefix="/users/me")
router = BaseRouter(router=me_router_instance, default_tags=["me"])


@router.get("/profile")
async def get_my_profile(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the current user's profile page."""
    return APIResponse.html_response(
        template_name="me/profile.html",
        context={"user": user},  # request is passed as a named arg to html_response
        request=request,
    )


@router.get("/invitations")
async def list_my_invitations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing the current user's pending invitations."""
    invitations = await handle_get_my_invitations(user=user, user_service=user_service)
    return APIResponse.html_response(
        template_name="me/invitations.html",
        context={"invitations": invitations},
        request=request,
    )


@router.get("/conversations")
async def list_my_conversations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing conversations the current user is part of."""
    conversations = await handle_get_my_conversations(
        user=user, user_service=user_service
    )
    return APIResponse.html_response(
        template_name="me/conversations.html",
        context={"conversations": conversations},
        request=request,
    )


# In main.py or similar, you would import and include me_router_instance:
# from src.api.routes.me import me_router_instance
# app.include_router(me_router_instance)
