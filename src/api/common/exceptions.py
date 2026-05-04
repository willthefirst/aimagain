import logging

from fastapi import HTTPException, status
from fastapi_users import exceptions as fastapi_users_exceptions
from fastapi_users.router.common import ErrorCode

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


def handle_fastapi_users_error(e: fastapi_users_exceptions.FastAPIUsersException):
    """
    Maps fastapi-users exceptions to APIException responses.

    Called by the @handle_route_errors decorator. fastapi-users raises its
    own exception types from the registration/auth flow; this maps the two
    we care about to the API response shapes the frontend expects. Other
    FastAPIUsersException subclasses fall through and the caller re-raises
    them as a generic 500.
    """
    logger.warning(f"Handling fastapi-users error: {e.__class__.__name__} - {e}")

    if isinstance(e, fastapi_users_exceptions.UserAlreadyExists):
        raise APIException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.REGISTER_USER_ALREADY_EXISTS,
        )
    elif isinstance(e, fastapi_users_exceptions.InvalidPasswordException):
        raise BadRequestError(
            detail={
                "code": ErrorCode.REGISTER_INVALID_PASSWORD,
                "reason": e.reason,
            }
        )
