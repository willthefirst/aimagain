from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse

from sqlalchemy.ext.asyncio import AsyncSession

# Import templates from the new core location
from app.core.templating import templates
# Import DB dependency function and User model
from app.db import get_db
from app.models import User, Conversation, Participant
from sqlalchemy import select, func # Import select, func

router = APIRouter()

# Specify HTMLResponse as the default response class for this endpoint
@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    participated_with: str | None = None # Add query parameter
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    """
    # Placeholder for current user - needed for participated_with filter
    stmt = select(User).filter(User.username == "test-user-me")
    result = await db.execute(stmt)
    current_user = result.scalars().first()
    # if not current_user and participated_with == "me":
    #     raise HTTPException(status_code=403, detail="Authentication required for this filter")

    if participated_with == "me":
        if not current_user:
             raise HTTPException(status_code=403, detail="Authentication required for this filter (placeholder)")

        # Find IDs of conversations 'me' has joined
        my_joined_convo_ids_subquery = (
            select(Participant.conversation_id)
            .filter(Participant.user_id == current_user.id)
            .filter(Participant.status == 'joined')
            .scalar_subquery() # Get a subquery usable in IN clause
        )

        # Find IDs of users (excluding 'me') who are also 'joined' in those conversations
        other_user_ids_subquery = (
            select(Participant.user_id)
            .filter(Participant.conversation_id.in_(my_joined_convo_ids_subquery))
            .filter(Participant.user_id != current_user.id)
            .filter(Participant.status == 'joined')
            .distinct()
            .scalar_subquery()
        )

        stmt = select(User).filter(User.id.in_(other_user_ids_subquery))

        # Fetch the User objects for those IDs
        result = await db.execute(stmt)
        users = result.scalars().all()
        return users
    else:
        # Original query: List all users
        # TODO: Add sorting later if needed (e.g., by username)
        result = await db.execute(select(User)) 
        users = result.scalars().all()

    return templates.TemplateResponse(
        name="users/list.html",
        context={"request": request, "users": users}
    )