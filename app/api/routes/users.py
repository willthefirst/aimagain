import logging  # Add logging
from fastapi import APIRouter, Request, Depends, HTTPException, status  # Add status
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
from app.auth_config import current_active_user  # New import
from app.logic.user_processing import handle_list_users  # Import the new handler

# from app.services.exceptions import ServiceError, DatabaseError # Placeholder if specific errors are raised by handler

router = APIRouter()
logger = logging.getLogger(__name__)  # Add logger


@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),  # Require authentication
    participated_with: str | None = None,
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    Requires authentication.
    Uses a logic handler to fetch and prepare user data.
    """
    try:
        # Call the logic handler to get user list and context
        context = await handle_list_users(
            request=request,
            user_repo=user_repo,
            requesting_user=user,
            participated_with_filter=participated_with,
        )
        return templates.TemplateResponse("users/list.html", context)

    # Example of handling specific errors if the handler were to raise them:
    # except UserNotFoundError as e: # Assuming a custom UserNotFoundError from logic layer
    #     logger.info(f"User-related data not found: {e}")
    #     raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    # except UserProcessingError as e: # Assuming a base custom error
    #     logger.error(f"Error processing user request: {e}", exc_info=True)
    #     # Potentially use a helper like handle_service_error if it becomes general
    #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        # Catch-all for other errors, including those propagated from the repository
        # or unexpected errors in the handler.
        logger.error(f"Unexpected error in list_users route: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected server error occurred while trying to list users.",
        )


# The old code block is removed as its logic is now in handle_list_users
# current_user = user

# filter_user = None
# if participated_with == "me":
# filter_user = current_user
# elif participated_with:
# pass

# users = await user_repo.list_users(
# exclude_user=current_user,
# participated_with_user=filter_user,
# )

# return templates.TemplateResponse(
# "users/list.html", {"request": request, "users": users}
# )
