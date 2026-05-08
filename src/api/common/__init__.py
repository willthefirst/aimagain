# This file makes src/api/common a Python package

from .base_router import BaseRouter
from .decorators import handle_route_errors
from .exceptions import (
    APIException,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    handle_fastapi_users_error,
)
from .forms import parse_form_to_payload, validate_or_422
from .responses import APIResponse

__all__ = [
    "APIResponse",
    "handle_route_errors",
    "APIException",
    "NotFoundError",
    "BadRequestError",
    "ForbiddenError",
    "handle_fastapi_users_error",
    "BaseRouter",
    "parse_form_to_payload",
    "validate_or_422",
]
