import logging

from fastapi import HTTPException, status

# Assuming ServiceError and its subclasses are defined in app.services.exceptions
from app.services.exceptions import BusinessRuleError  # Example, add others as needed
from app.services.exceptions import (
    ConflictError,
    ConversationNotFoundError,
    DatabaseError,
    NotAuthorizedError,
    ParticipantNotFoundError,
    ServiceError,
    UserNotFoundError,
)

logger = logging.getLogger(__name__)


class APIException(HTTPException):
    """Base class for API specific exceptions."""

    def __init__(
        self, status_code: int, detail: any = None, headers: dict | None = None
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class NotFoundError(APIException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class BadRequestError(APIException):
    def __init__(self, detail: str = "Bad request"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class UnauthorizedError(APIException):
    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class ForbiddenError(APIException):
    def __init__(self, detail: str = "Forbidden"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class InternalServerError(APIException):
    def __init__(self, detail: str = "Internal server error"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail
        )


def handle_service_error(e: ServiceError):
    """
    Maps ServiceError subclasses to appropriate APIException or HTTPException.
    This function is expected to be called by the @handle_route_errors decorator.
    It standardizes how service layer errors are translated into HTTP responses.
    """
    logger.warning(
        f"Handling service error: {e.__class__.__name__} - {getattr(e, 'message', str(e))}"
    )

    if (
        isinstance(e, ConversationNotFoundError)
        or isinstance(e, ParticipantNotFoundError)
        or isinstance(e, UserNotFoundError)
    ):
        raise NotFoundError(detail=getattr(e, "message", str(e)))
    elif isinstance(e, NotAuthorizedError):
        raise ForbiddenError(
            detail=getattr(e, "message", str(e))
        )  # Or UnauthorizedError depending on specific meaning
    elif isinstance(e, BusinessRuleError):
        raise BadRequestError(
            detail=getattr(e, "message", str(e))
        )  # Or a 422 if it's a validation rule
    elif isinstance(e, ConflictError):
        raise APIException(
            status_code=status.HTTP_409_CONFLICT, detail=getattr(e, "message", str(e))
        )
    elif isinstance(e, DatabaseError):
        # Potentially log more details for database errors, but don't expose them to the client
        logger.error(f"Database error: {e}", exc_info=True)
        raise InternalServerError(detail="A database error occurred.")
    elif isinstance(e, ServiceError):
        # For generic ServiceErrors, use their proposed status code if available, or default
        status_code = getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
        raise APIException(
            status_code=status_code,
            detail=getattr(e, "message", "A service error occurred."),
        )
    else:
        # Fallback for unmapped errors, though @handle_route_errors should catch generic Exception
        logger.error(
            f"Unhandled service error type: {type(e).__name__} - {e}", exc_info=True
        )
        raise InternalServerError(
            detail="An unexpected error occurred at the service layer."
        )
