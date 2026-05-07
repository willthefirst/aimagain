# This file makes src/api/common a Python package

from .base_router import BaseRouter
from .decorators import handle_route_errors, log_route_call
from .exceptions import (
    APIException,
    BadRequestError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    UnauthorizedError,
    handle_fastapi_users_error,
)
from .forms import parse_form_to_payload, validate_or_422
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
    "handle_fastapi_users_error",
    "BaseRouter",
    "parse_form_to_payload",
    "validate_or_422",
]
