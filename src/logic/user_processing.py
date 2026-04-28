import logging

from fastapi import Request

from src.models import User
from src.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def handle_list_users(
    request: Request,
    user_repo: UserRepository,
    requesting_user: User,
):
    """
    Handles the core logic for listing users.

    Args:
        request: The FastAPI request object.
        user_repo: The user repository dependency.
        requesting_user: The currently authenticated user.

    Returns:
        A dictionary containing the context for the template.

    Raises:
        Exception: Propagates exceptions from the repository layer.
    """
    logger.debug(f"Handler: Listing users for user {requesting_user.id}.")

    try:
        users_list = await user_repo.list_users(
            exclude_user=requesting_user,
        )
    except Exception as e:
        logger.error(
            f"Handler: Error listing users from repository: {e}", exc_info=True
        )
        raise

    logger.debug(
        f"Handler: Successfully retrieved {len(users_list)} users for user {requesting_user.id}."
    )

    return {"request": request, "users": users_list, "current_user": requesting_user}
