import logging

from fastapi import Request

from app.models import User
from app.repositories.user_repository import UserRepository

# Potentially import custom exceptions if needed, e.g.:
# from app.services.exceptions import ServiceError, DatabaseError

logger = logging.getLogger(__name__)


# Define custom exceptions for this logic layer if they become necessary
# class UserProcessingError(Exception):
#     """Base exception for user processing logic errors."""
#     pass

# class UserNotFoundError(UserProcessingError):
#     """Custom exception for user not found in this logic layer."""
#     pass


async def handle_list_users(
    request: Request,
    user_repo: UserRepository,
    requesting_user: User,
    participated_with_filter: str | None = None,
):
    """
    Handles the core logic for listing users, applying filters as specified.

    Args:
        request: The FastAPI request object.
        user_repo: The user repository dependency.
        requesting_user: The currently authenticated user.
        participated_with_filter: Optional filter string (e.g., "me").

    Returns:
        A dictionary containing the context for the template.

    Raises:
        # Define and raise specific exceptions if error conditions
        # handled here warrant it (e.g., UserProcessingError).
        # For now, repository errors will propagate.
        Exception: Propagates exceptions from the repository layer.
    """
    logger.debug(
        f"Handler: Listing users for user {requesting_user.id}. Filter: {participated_with_filter}"
    )

    filter_user_for_participation = None
    if participated_with_filter == "me":
        filter_user_for_participation = requesting_user
    elif participated_with_filter:
        # Silently ignore invalid filter values for now, or log/raise an error.
        logger.warning(
            f"Invalid 'participated_with' filter value received: {participated_with_filter}"
        )
        # Optionally, you could raise a BusinessRuleError or similar here
        # if strict validation is required. For example:
        # raise BusinessRuleError(f"Invalid filter option: {participated_with_filter}")

    try:
        users_list = await user_repo.list_users(
            exclude_user=requesting_user,  # Exclude current user
            participated_with_user=filter_user_for_participation,
        )
    except Exception as e:
        # Log and re-raise repository/database errors
        logger.error(
            f"Handler: Error listing users from repository: {e}", exc_info=True
        )
        # Depending on desired error handling, you might wrap this in a
        # custom ServiceError or DatabaseError defined for this layer/service.
        raise  # Re-raise the original exception for the route to handle

    logger.info(
        f"Handler: Successfully retrieved {len(users_list)} users for user {requesting_user.id}."
    )

    return {"request": request, "users": users_list, "current_user": requesting_user}
