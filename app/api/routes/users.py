from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse

# Removed unused SQLAlchemy imports
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from sqlalchemy.orm import selectinload, joinedload

from app.core.templating import templates

# Updated db dependency import -> No longer needed
# from app.db import get_db_session
from app.repositories.dependencies import get_user_repository  # Import repo dependency
from app.repositories.user_repository import UserRepository  # Import repo type
from app.models import User  # Keep User for type hint

router = APIRouter()


@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    # Inject repository
    user_repo: UserRepository = Depends(get_user_repository),
    # db: AsyncSession = Depends(get_db_session), # Remove direct session dependency
    participated_with: str | None = None,
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    """
    # Placeholder for current user
    # TODO: Replace with actual authenticated user dependency
    current_user = await user_repo.get_user_by_username("test-user-me")

    filter_user = None
    if participated_with == "me":
        if not current_user:
            raise HTTPException(
                status_code=403,
                detail="Cannot filter by participation without auth (placeholder)",
            )
        filter_user = current_user
    elif participated_with:
        # Silently ignore invalid filter values for now, or raise error
        pass

    # Use the repository method to get the list of users
    users = await user_repo.list_users(
        exclude_user=current_user,  # Exclude current user if authenticated
        participated_with_user=filter_user,  # Apply participation filter if requested
    )

    return templates.TemplateResponse(
        "users/list.html", {"request": request, "users": users}
    )
