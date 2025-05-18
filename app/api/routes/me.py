import logging

from fastapi import APIRouter, Depends, Request

from app.api.common import APIResponse, BaseRouter
from app.auth_config import current_active_user
from app.logic.me_processing import (
    handle_get_my_conversations,
    handle_get_my_invitations,
)
from app.models import User
from app.services.dependencies import get_user_service
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

# 1. Create the APIRouter. This instance will be imported and included in the main FastAPI app.
#    It defines the prefix for all routes in this file.
me_router_instance = APIRouter(prefix="/users/me")

# 2. Create a BaseRouter helper, passing it the actual APIRouter instance and default tags.
#    Route definitions below will use this `router` helper.
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
# from app.api.routes.me import me_router_instance
# app.include_router(me_router_instance)
