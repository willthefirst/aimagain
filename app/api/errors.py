import logging
from fastapi import HTTPException

# Import base ServiceError from the new location
from app.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


def handle_service_error(e: ServiceError):
    """Maps ServiceError subclasses to appropriate HTTPException responses."""
    logger.warning(
        f"Service error occurred: {e.__class__.__name__} - {e.message}"
    )  # Log service errors
    raise HTTPException(status_code=e.status_code, detail=e.message)


# You could add more specific handlers or general exception handlers here if needed
