import logging
from functools import wraps

from fastapi import HTTPException, status

from app.api.errors import handle_service_error
from app.services.exceptions import (
    BusinessRuleError,
    ConflictError,
    ConversationNotFoundError,
    DatabaseError,
    NotAuthorizedError,
    ParticipantNotFoundError,
    ServiceError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


def handle_route_errors(func):
    """
    A decorator to standardize error handling in API routes.
    It catches common service-layer exceptions and a generic Exception,
    logs them, and then either calls a specific handler (handle_service_error)
    or raises an appropriate HTTPException.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except (
            BusinessRuleError,
            ConflictError,
            ConversationNotFoundError,
            DatabaseError,
            NotAuthorizedError,
            ParticipantNotFoundError,
            UserNotFoundError,
        ) as e:
            # These are specific custom errors that handle_service_error knows about
            # or that result in specific HTTP statuses.
            logger.error(
                f"Service error in {func.__name__} route: {e}", exc_info=False
            )  # Keep log cleaner
            handle_service_error(e)  # This function is expected to raise HTTPException
        except ServiceError as e:  # Catch-all for other service errors
            logger.error(
                f"Generic service error in {func.__name__} route: {e}", exc_info=True
            )
            handle_service_error(e)
        except HTTPException as e:
            # If an HTTPException is raised directly, just re-raise it.
            # This can happen if a route explicitly raises one for validation, etc.
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in {func.__name__} route: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected server error occurred.",
            )

    return wrapper
