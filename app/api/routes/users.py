from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload  # Import selectinload if needed later

# Import templates from the new core location
from app.core.templating import templates

# Import DB dependency function and User model
from app.db import get_db  # Use async db dependency
from app.models import User, Conversation, Participant
from sqlalchemy import select, func  # Import select, func

router = APIRouter()


# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),  # Use async db dependency
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
    # Note: No exception raised here if user not found, handled below

    users = []  # Initialize users list
    if participated_with == "me":
        if not current_user:
            raise HTTPException(
                status_code=403,
                detail="Authentication required for this filter (placeholder)",
            )

        # Find IDs of conversations 'me' has joined
        my_joined_convo_ids_stmt = (
            select(Participant.conversation_id)
            .where(Participant.user_id == current_user.id)
            .where(Participant.status == "joined")
        )
        my_joined_convo_ids_result = await db.execute(my_joined_convo_ids_stmt)
        my_joined_convo_ids = my_joined_convo_ids_result.scalars().all()

        if not my_joined_convo_ids:
            # If the user hasn't joined any conversations, the list is empty
            users = []
        else:
            # Find IDs of users (excluding 'me') who are also 'joined' in those conversations
            other_user_ids_stmt = (
                select(Participant.user_id)
                .where(Participant.conversation_id.in_(my_joined_convo_ids))
                .where(Participant.user_id != current_user.id)
                .where(Participant.status == "joined")
                .distinct()
            )
            other_user_ids_result = await db.execute(other_user_ids_stmt)
            other_user_ids = other_user_ids_result.scalars().all()

            if not other_user_ids:
                users = []
            else:
                # Fetch the User objects for those IDs
                users_stmt = select(User).where(User.id.in_(other_user_ids))
                users_result = await db.execute(users_stmt)
                users = users_result.scalars().all()

    else:
        # Original query: List all users
        # TODO: Add sorting later if needed (e.g., by username)
        all_users_stmt = select(User)
        all_users_result = await db.execute(all_users_stmt)
        users = all_users_result.scalars().all()

    return templates.TemplateResponse(
        name="users/list.html", context={"request": request, "users": users}
    )
