# Convenience re-exports for the most-used framework symbols.

from .dispatch.base_router import BaseRouter
from .dispatch.registry import register_entity
from .http.decorators import handle_route_errors
from .http.exceptions import (
    APIException,
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    handle_fastapi_users_error,
)
from .http.forms import parse_and_validate_form, parse_form_to_payload, validate_or_422
from .http.responses import (
    APIResponse,
    created_response,
    deleted_response,
    refreshed_response,
    updated_response,
)

__all__ = [
    "APIException",
    "APIResponse",
    "BadRequestError",
    "BaseRouter",
    "ForbiddenError",
    "NotFoundError",
    "created_response",
    "deleted_response",
    "handle_fastapi_users_error",
    "handle_route_errors",
    "parse_and_validate_form",
    "parse_form_to_payload",
    "refreshed_response",
    "register_entity",
    "updated_response",
    "validate_or_422",
]
