import logging
from functools import wraps


def log_route_call(func):
    """
    A decorator to log the entry and exit of a route function.
    It logs the function name, arguments, and whether it completed successfully or raised an error.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        logger = logging.getLogger(
            func.__module__
        )  # Use the logger of the decorated function's module

        # Prepare args and kwargs for logging (avoid logging sensitive data if necessary)
        # For simplicity, logging all for now. In a real app, filter sensitive info.
        logged_args = [repr(a) for a in args]
        logged_kwargs = {k: repr(v) for k, v in kwargs.items()}

        logger.info(
            f"Entering route: {func.__name__} (args: {logged_args}, kwargs: {logged_kwargs})"
        )
        try:
            result = await func(*args, **kwargs)
            logger.info(f"Successfully exited route: {func.__name__}")
            return result
        except Exception as e:
            # Error is already logged by handle_route_errors if used,
            # but we log that an error occurred during the call here.
            logger.error(
                f"Error during route: {func.__name__}. Exception: {type(e).__name__} - {e}",
                exc_info=False,
            )
            raise  # Re-raise the exception to be handled by other decorators or FastAPI

    return wrapper
