from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse

# Removed unused imports
# from selectolax.parser import HTMLParser
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload

from app.core.templating import templates

# Remove direct db dependency
# from app.db import get_db_session
from app.models import User  # Keep User for type hint

# Import repositories
from app.repositories.dependencies import (
    get_user_repository,
    get_participant_repository,
    get_conversation_repository,
)
from app.repositories.user_repository import UserRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.conversation_repository import ConversationRepository


router = APIRouter(prefix="/users/me", tags=["me"])


@router.get("/profile", response_class=HTMLResponse)
async def get_my_profile(request: Request):
    """Placeholder for the user's profile page."""
    # TODO: Fetch actual user data later using UserRepository
    user = {"username": "test-user-me", "email": "me@example.com"}
    return templates.TemplateResponse(
        "me/profile.html", {"request": request, "user": user}
    )


@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(
    request: Request,
    # Inject repositories
    user_repo: UserRepository = Depends(get_user_repository),
    part_repo: ParticipantRepository = Depends(get_participant_repository),
    # db: AsyncSession = Depends(get_db_session) # Remove direct session
):
    print("Listing my invitations")  # Keep existing print
    """Provides an HTML page listing the current user's pending invitations."""
    # TODO: Replace placeholder with actual authenticated user logic
    current_user = await user_repo.get_user_by_username("test-user-me")

    if not current_user:
        raise HTTPException(status_code=403, detail="User not found (placeholder)")

    # Use repository to get invitations
    invitations = await part_repo.list_user_invitations(user=current_user)

    return templates.TemplateResponse(
        "me/invitations.html",
        {"request": request, "invitations": invitations},
    )


@router.get("/conversations", response_class=HTMLResponse)
async def list_my_conversations(
    request: Request,
    # Inject repositories
    user_repo: UserRepository = Depends(get_user_repository),
    conv_repo: ConversationRepository = Depends(get_conversation_repository),
    # db: AsyncSession = Depends(get_db_session) # Remove direct session
):
    """Provides an HTML page listing conversations the current user is part of."""
    # TODO: Replace placeholder with actual authenticated user logic
    current_user = await user_repo.get_user_by_username("test-user-me")

    if not current_user:
        raise HTTPException(status_code=403, detail="User not found (placeholder)")

    # Use repository to get conversations
    conversations = await conv_repo.list_user_conversations(user=current_user)

    return templates.TemplateResponse(
        "me/conversations.html",
        {"request": request, "conversations": conversations},
    )
