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

router = APIRouter(
    prefix="/me",
    tags=["me"]
)

@router.get("/invitations", response_class=HTMLResponse)
async def list_my_invitations(request: Request, db: AsyncSession = Depends(get_db)):
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
            selectinload(Participant.conversation).selectinload(Conversation.created_by),
            selectinload(Participant.initial_message),
            selectinload(Participant.invited_by)
        )
        .order_by(Participant.created_at.desc()) # Example sort
    )
    invitations_result = await db.execute(invitations_stmt)
    invitations = invitations_result.scalars().all()

    return templates.TemplateResponse(
        "me/list_invitations.html",
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
        .where(Participant.user_id == current_user.id)
        .where(Participant.status == "joined") # Assuming 'joined' means part of it
        .options(
            selectinload(Participant.conversation)
            # Add other eager loads if needed by the template
            .selectinload(Conversation.last_message),
             selectinload(Participant.conversation)
            .selectinload(Conversation.participants).selectinload(Participant.user)
        )
        .order_by(Participant.conversation.last_activity_at.desc()) # Sort by most recent activity
    )
    participants_result = await db.execute(conversations_stmt)
    participants = participants_result.scalars().unique().all()

    return templates.TemplateResponse(
        "me/list_conversations.html",
        {"request": request, "participants": participants}
    ) 