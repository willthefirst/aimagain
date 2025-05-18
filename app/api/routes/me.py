import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.errors import handle_service_error
from app.auth_config import current_active_user
from app.core.templating import templates
from app.logic.me_processing import (
    handle_get_my_conversations,
    handle_get_my_invitations,
)
from app.models import User
from app.services.dependencies import get_user_service
from app.services.exceptions import DatabaseError, ServiceError
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["me"])


@router.get("/profile", response_class=HTMLResponse)
async def get_my_profile(
    request: Request,
    user: User = Depends(current_active_user),
):
    """Displays the current user's profile page."""
    return templates.TemplateResponse(
        "me/profile.html", {"request": request, "user": user}
    )


@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing the current user's pending invitations."""
    try:
        invitations = await handle_get_my_invitations(
            user=user, user_service=user_service
        )
        return templates.TemplateResponse(
            "me/invitations.html",
            {"request": request, "invitations": invitations},
        )
    except DatabaseError as e:
        logger.error(
            f"Database error in list_my_invitations route for user {user.id}: {e}",
            exc_info=True,
        )
        handle_service_error(e)
    except ServiceError as e:
        logger.error(
            f"Service error in list_my_invitations route for user {user.id}: {e}",
            exc_info=True,
        )
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error listing invitations for user {user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )


@router.get("/conversations", response_class=HTMLResponse)
async def list_my_conversations(
    request: Request,
    user: User = Depends(current_active_user),
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing conversations the current user is part of."""
    try:
        conversations = await handle_get_my_conversations(
            user=user, user_service=user_service
        )
        return templates.TemplateResponse(
            "me/conversations.html",
            {"request": request, "conversations": conversations},
        )
    except DatabaseError as e:
        logger.error(
            f"Database error in list_my_conversations route for user {user.id}: {e}",
            exc_info=True,
        )
        handle_service_error(e)
    except ServiceError as e:
        logger.error(
            f"Service error in list_my_conversations route for user {user.id}: {e}",
            exc_info=True,
        )
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error listing conversations for user {user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )
