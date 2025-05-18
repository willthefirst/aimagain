import logging
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from app.core.templating import templates
from app.repositories.dependencies import get_user_repository
from app.repositories.user_repository import UserRepository
from app.models import User
from app.auth_config import current_active_user
from app.logic.user_processing import handle_list_users

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/users", response_class=HTMLResponse, tags=["users"])
async def list_users(
    request: Request,
    user_repo: UserRepository = Depends(get_user_repository),
    user: User = Depends(current_active_user),
    participated_with: str | None = None,
):
    """Provides an HTML page listing registered users.
    Can be filtered to users participated with the current user.
    Requires authentication.
    Uses a logic handler to fetch and prepare user data.
    """
    try:
        context = await handle_list_users(
            request=request,
            user_repo=user_repo,
            requesting_user=user,
            participated_with_filter=participated_with,
        )
        return templates.TemplateResponse("users/list.html", context)

    except Exception as e:
        logger.error(f"Unexpected error in list_users route: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected server error occurred while trying to list users.",
        )
