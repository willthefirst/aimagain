# Convenience re-exports for the most-used framework symbols.

from .base_router import BaseRouter, make_entity_router
from .decorators import handle_route_errors
from .exceptions import (
    APIException,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    handle_fastapi_users_error,
)
from .forms import parse_and_validate_form, parse_form_to_payload, validate_or_422
from .responses import (
    APIResponse,
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)

__all__ = [
    "APIResponse",
    "handle_route_errors",
    "APIException",
    "NotFoundError",
    "BadRequestError",
    "ForbiddenError",
    "handle_fastapi_users_error",
    "BaseRouter",
    "make_entity_router",
    "created_response",
    "deleted_response",
    "parse_and_validate_form",
    "parse_form_to_payload",
    "refreshed_response",
    "updated_response",
    "validate_or_422",
]
