from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload, joinedload

from app.core.templating import templates

# Updated db dependency import
from app.db import get_db_session
from app.models import (
    User,
    Participant,
    Conversation,
)  # Added Participant, Conversation

router = APIRouter()


@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db_session),  # Use get_db_session
    participated_with: str | None = None,  # Add query parameter
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    """
    # Placeholder for current user - needed for participated_with filter
    # Use a consistent placeholder user or implement proper auth
    current_user_stmt = select(User).filter(User.username == "test-user-me")
    current_user_result = await db.execute(current_user_stmt)
    current_user = current_user_result.scalars().first()

    if participated_with == "me" and not current_user:
        raise HTTPException(
            status_code=403,
            detail="Cannot filter by participation without auth (placeholder)",
        )

    stmt = select(User)

    if participated_with == "me" and current_user:
        # Find conversations current user is joined in
        joined_conv_subq = (
            select(Participant.conversation_id)
            .where(
                Participant.user_id == current_user.id,
                Participant.status == "joined",
            )
            .subquery()
        )

        # Find users who are also joined in those conversations
        participating_user_ids_stmt = (
            select(Participant.user_id)
            .where(
                Participant.conversation_id.in_(select(joined_conv_subq)),
                Participant.user_id != current_user.id,  # Exclude the current user
                Participant.status == "joined",
            )
            .distinct()
        )
        # Execute the subquery to get the IDs
        participating_user_ids_result = await db.execute(participating_user_ids_stmt)
        participating_user_ids = participating_user_ids_result.scalars().all()

        # Filter the main user query by these IDs
        stmt = stmt.filter(User.id.in_(participating_user_ids))
    elif participated_with:
        # Handle invalid filter values if needed
        pass  # Or raise HTTPException for invalid filter value

    # Always exclude the current user from the main list if authenticated
    if current_user:
        stmt = stmt.filter(User.id != current_user.id)

    stmt = stmt.order_by(User.username)
    result = await db.execute(stmt)
    users = result.scalars().all()

    return templates.TemplateResponse(
        "users/list.html", {"request": request, "users": users}
    )
