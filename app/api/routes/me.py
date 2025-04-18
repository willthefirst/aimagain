from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from selectolax.parser import HTMLParser

# Import async session and select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.templating import templates
from app.db import get_db_session
from app.models import (
    User,
    Participant,
    Conversation,
    Message,
)  # Ensure all models imported

# TODO: move this inside /users router?
router = APIRouter(prefix="/users/me", tags=["me"])


@router.get("/profile", response_class=HTMLResponse)
async def get_my_profile(request: Request):
    """Placeholder for the user's profile page."""
    # TODO: Fetch actual user data later
    user = {"username": "test-user-me", "email": "me@example.com"}
    return templates.TemplateResponse(
        "me/profile.html", {"request": request, "user": user}
    )


@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(
    request: Request, db: AsyncSession = Depends(get_db_session)
):
    print("Listing my invitations")
    """Provides an HTML page listing the current user's pending invitations."""
    # TODO: Replace placeholder with actual authenticated user logic
    # Placeholder: Query for a user with a specific username used in tests
    current_user_stmt = select(User).filter(User.username == "test-user-me")
    current_user_result = await db.execute(current_user_stmt)
    current_user = current_user_result.scalars().first()

    if not current_user:
        # In a real app, an unauthenticated user shouldn't reach here
        # This is primarily for the placeholder logic to work in tests
        raise HTTPException(status_code=403, detail="User not found (placeholder)")

    # Query for invitations for the current user
    invitations_stmt = (
        select(Participant)
        .where(
            Participant.user_id == current_user.id,
            Participant.status == "invited",  # Only show pending invitations
        )
        .options(
            selectinload(Participant.conversation).selectinload(Conversation.creator),
            selectinload(Participant.inviter),  # Correct relationship name
            selectinload(Participant.initial_message),
        )
        # Use explicit table column reference for ordering
        .order_by(Participant.__table__.c.created_at.desc())
    )

    invitations_result = await db.execute(invitations_stmt)
    invitations = invitations_result.scalars().all()

    return templates.TemplateResponse(
        "me/invitations.html",
        {"request": request, "invitations": invitations},
    )


@router.get("/conversations", response_class=HTMLResponse)
async def list_my_conversations(
    request: Request, db: AsyncSession = Depends(get_db_session)
):
    """Provides an HTML page listing conversations the current user is part of."""
    # Placeholder for current user (same as above)
    current_user_stmt = select(User).filter(User.username == "test-user-me")
    current_user_result = await db.execute(current_user_stmt)
    current_user = current_user_result.scalars().first()

    if not current_user:
        raise HTTPException(status_code=403, detail="User not found (placeholder)")

    # Query for conversations the user is a 'joined' participant in
    conversations_stmt = (
        select(Conversation)
        .join(Participant, Conversation.id == Participant.conversation_id)
        .filter(
            Participant.user_id == current_user.id,
            Participant.status == "joined",  # Only conversations they've joined
        )
        .options(
            selectinload(Conversation.participants).joinedload(
                Participant.user
            ),  # Load participants and their users
            # Optionally load last message snippet if needed by template
            # selectinload(Conversation.messages).options(load_only(Message.content, Message.created_at)).order_by(Message.created_at.desc()).limit(1)
        )
        .order_by(Conversation.last_activity_at.desc().nullslast())
    )

    conversations_result = await db.execute(conversations_stmt)
    conversations = conversations_result.scalars().unique().all()

    return templates.TemplateResponse(
        "me/conversations.html",
        {"request": request, "conversations": conversations},
    )
