# This file makes app/api/common a Python package

from .base_router import BaseRouter
from .decorators import handle_route_errors, log_route_call
from .exceptions import (
    APIException,
    BadRequestError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    UnauthorizedError,
    handle_service_error,
)
from .responses import APIResponse

__all__ = [
    "APIResponse",
    "log_route_call",
    "handle_route_errors",
    "APIException",
    "NotFoundError",
    "BadRequestError",
    "UnauthorizedError",
    "ForbiddenError",
    "InternalServerError",
    "handle_service_error",
    "BaseRouter",
]
