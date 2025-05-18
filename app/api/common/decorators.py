import logging
from functools import wraps

from fastapi import HTTPException, status

from app.api.common.exceptions import handle_service_error
from app.services.exceptions import (  # Assuming these are general service exceptions
    BusinessRuleError,
    ConflictError,
    ConversationNotFoundError,
    DatabaseError,
    NotAuthorizedError,
    ParticipantNotFoundError,
    ServiceError,
    UserNotFoundError,
)

# This will be moved to app.api.common.exceptions soon
# from app.api.errors import handle_service_error
# For now, let's assume it's available or define a placeholder if necessary
# We'll need to adjust imports once app.api.common.exceptions is created
# and handle_service_error is moved there.


logger = logging.getLogger(__name__)


def log_route_call(func):
    """
    A decorator to log the entry and exit of a route function.
    It logs the function name, arguments, and whether it completed successfully or raised an error.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Use the logger of the decorated function's module for better context
        # However, for a common decorator, using its own module's logger is also fine.
        # Let's use the common logger here.
        route_logger = logging.getLogger(func.__module__)

        # Prepare args and kwargs for logging (avoid logging sensitive data if necessary)
        # For simplicity, logging all for now. In a real app, filter sensitive info.
        logged_args = [repr(a) for a in args]
        logged_kwargs = {k: repr(v) for k, v in kwargs.items()}

        route_logger.info(
            f"Entering route: {func.__name__} (args: {logged_args}, kwargs: {logged_kwargs})"
        )
        try:
            result = await func(*args, **kwargs)
            route_logger.info(f"Successfully exited route: {func.__name__}")
            return result
        except Exception as e:
            route_logger.error(
                f"Error during route: {func.__name__}. Exception: {type(e).__name__} - {e}",
                exc_info=False,  # Set to True if full traceback is needed here, handle_route_errors might log it too
            )
            raise

    return wrapper


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
            logger.error(f"Service error in {func.__name__} route: {e}", exc_info=False)
            handle_service_error(e)  # This function is expected to raise HTTPException
        except ServiceError as e:  # Catch-all for other service errors
            logger.error(
                f"Generic service error in {func.__name__} route: {e}", exc_info=True
            )
            handle_service_error(e)
        except HTTPException as e:
            # If an HTTPException is raised directly, just re-raise it.
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
