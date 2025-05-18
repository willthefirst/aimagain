import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.decorators import handle_route_errors
from app.api.logging import log_route_call
from app.api.responses import html_response
from app.auth_config import current_active_user
from app.logic.me_processing import (
    handle_get_my_conversations,
    handle_get_my_invitations,
)
from app.models import User
from app.services.dependencies import get_user_service
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["me"])


@router.get("/profile", response_class=HTMLResponse)
@log_route_call
async def get_my_profile(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the current user's profile page."""
    return html_response(
        template_name="me/profile.html", context={"user": user}, request=request
    )


@router.get("/invitations", response_class=HTMLResponse)
@log_route_call
@handle_route_errors
async def list_my_invitations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing the current user's pending invitations."""
    invitations = await handle_get_my_invitations(user=user, user_service=user_service)
    return html_response(
        template_name="me/invitations.html",
        context={"invitations": invitations},
        request=request,
    )


@router.get("/conversations", response_class=HTMLResponse)
@log_route_call
@handle_route_errors
async def list_my_conversations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing conversations the current user is part of."""
    conversations = await handle_get_my_conversations(
        user=user, user_service=user_service
    )
    return html_response(
        template_name="me/conversations.html",
        context={"conversations": conversations},
        request=request,
    )
