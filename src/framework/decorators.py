import logging
from functools import wraps

from fastapi import HTTPException, status
from fastapi_users import exceptions as fastapi_users_exceptions

from src.framework.exceptions import handle_fastapi_users_error

logger = logging.getLogger(__name__)


def log_route_call(func):
    """
    A decorator to log the entry and exit of a route function.
    It logs the function name, arguments, and whether it completed successfully or raised an error.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        route_logger = logging.getLogger(func.__module__)

        route_logger.debug(f"Entering route: {func.__name__}")
        try:
            result = await func(*args, **kwargs)
            route_logger.debug(f"Successfully exited route: {func.__name__}")
            return result
        except Exception as e:
            route_logger.error(
                f"Error during route: {func.__name__}. Exception: {type(e).__name__} - {e}",
                exc_info=False,
            )
            raise

    return wrapper


def handle_route_errors(func):
    """
    A decorator to standardize error handling in API routes.

    Logic-layer ``handle_*`` functions raise APIException subclasses (e.g.
    ``NotFoundError``, ``ForbiddenError``) directly; those are HTTPException
    subclasses and pass through unchanged. fastapi-users raises its own
    exception types during registration/auth — those get translated by
    ``handle_fastapi_users_error``. Anything else becomes a 500.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except fastapi_users_exceptions.FastAPIUsersException as e:
            logger.warning(
                f"FastAPIUsers exception in {func.__name__} route: {type(e).__name__} - {e}"
            )
            handle_fastapi_users_error(e)
        except HTTPException:
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
