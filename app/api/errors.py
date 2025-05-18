import logging

from fastapi import HTTPException

from app.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


def handle_service_error(e: ServiceError):
    """Maps ServiceError subclasses to appropriate HTTPException responses."""
    logger.warning(f"Service error occurred: {e.__class__.__name__} - {e.message}")
    raise HTTPException(status_code=e.status_code, detail=e.message)
