from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from selectolax.parser import HTMLParser

# Import async session and select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.templating import templates
from app.db import get_db
from app.models import User, Participant, Conversation, Message # Ensure all models imported

# TODO: move this inside /users router?
router = APIRouter(
    prefix="/users/me",
    tags=["me"]
)

@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(request: Request, db: AsyncSession = Depends(get_db)):
    print("Listing my invitations")
    """Provides an HTML page listing the current user's pending invitations."""
    # TODO: Replace placeholder with actual authenticated user logic
    # Placeholder: Query for a user with a specific username used in tests
    current_user_stmt = select(User).filter(User.username == "test-user-me")
    current_user_result = await db.execute(current_user_stmt)
    current_user = current_user_result.scalars().first()

    if not current_user:
        # In a real app, this would likely redirect to login or be handled by middleware
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Query for invitations (Participant records where status is 'invited')
    invitations_stmt = (
        select(Participant)
        .where(Participant.user_id == current_user.id)
        .where(Participant.status == "invited")
        .options(
            selectinload(Participant.conversation).selectinload(Conversation.created_by_user_id),
            selectinload(Participant.initial_message),
            selectinload(Participant.inviter)
        )
        .order_by(Participant.created_at.desc()) # Example sort
    )
    invitations_result = await db.execute(invitations_stmt)
    invitations = invitations_result.scalars().all()
    print(f"Invitations: {invitations}")
    return templates.TemplateResponse(
        "me/invitations.html",
        {"request": request, "invitations": invitations}
    )

@router.get("/conversations", response_class=HTMLResponse)
async def list_my_conversations(request: Request, db: AsyncSession = Depends(get_db)):
    """Provides an HTML page listing conversations the current user is part of."""
    # Placeholder for current user (same as above)
    current_user_stmt = select(User).filter(User.username == "test-user-me")
    current_user_result = await db.execute(current_user_stmt)
    current_user = current_user_result.scalars().first()

    if not current_user:
        raise HTTPException(status_code=403, detail="Not authenticated (placeholder)")

    # Query for conversations the user is part of (e.g., status is 'joined')
    conversations_stmt = (
        select(Participant)
        .join(Participant.conversation)  # <-- Explicitly join Conversation
        .where(Participant.user_id == current_user.id)
        .where(Participant.status == "joined")
        .options(
            selectinload(Participant.conversation) # Still eager load the conversation object
            .selectinload(Conversation.participants).selectinload(Participant.user) # And its nested relationships
            # Removed the potentially problematic .selectinload(Conversation.last_activity_at)
        )
        .order_by(Conversation.last_activity_at.desc()) # <-- Order by the column on the joined table
    )
    participants_result = await db.execute(conversations_stmt)
    participants = participants_result.scalars().unique().all()

    return templates.TemplateResponse(
        "me/conversations.html",
        {"request": request, "participants": participants}
    ) 