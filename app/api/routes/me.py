from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
import logging

# Removed unused imports
# from selectolax.parser import HTMLParser
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload
# from app.db import get_db_session
# from app.repositories.dependencies import (
#     get_user_repository,
#     get_participant_repository,
#     get_conversation_repository,
# )
# from app.repositories.user_repository import UserRepository
# from app.repositories.participant_repository import ParticipantRepository
# from app.repositories.conversation_repository import ConversationRepository

from app.core.templating import templates
from app.models import User
from app.auth_config import current_active_user

# Import UserService dependency
from app.services.dependencies import get_user_service
from app.services.user_service import UserService
from app.services.exceptions import ServiceError, DatabaseError

# Import shared error handler
from app.api.errors import handle_service_error


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users/me", tags=["me"])


@router.get("/profile", response_class=HTMLResponse)
async def get_my_profile(
    request: Request,
    user: User = Depends(current_active_user),  # Get authenticated user
    # No service needed here, just returning the user object directly
):
    """Displays the current user's profile page."""
    return templates.TemplateResponse(
        "me/profile.html", {"request": request, "user": user}
    )


@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(
    request: Request,
    user: User = Depends(current_active_user),
    # Depend on the service
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing the current user's pending invitations."""
    try:
        invitations = await user_service.get_user_invitations(user=user)
        return templates.TemplateResponse(
            "me/invitations.html",
            {"request": request, "invitations": invitations},
        )
    except DatabaseError as e:
        handle_service_error(e)
    except ServiceError as e:
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
    # Depend on the service
    user_service: UserService = Depends(get_user_service),
):
    """Provides an HTML page listing conversations the current user is part of."""
    try:
        conversations = await user_service.get_user_conversations(user=user)
        return templates.TemplateResponse(
            "me/conversations.html",
            {"request": request, "conversations": conversations},
        )
    except DatabaseError as e:
        handle_service_error(e)
    except ServiceError as e:
        handle_service_error(e)
    except Exception as e:
        logger.error(
            f"Unexpected error listing conversations for user {user.id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="An unexpected server error occurred."
        )
