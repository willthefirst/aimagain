import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi_users import exceptions, models
from fastapi_users.manager import BaseUserManager
from fastapi_users.router.common import ErrorCode, ErrorModel

from app.api.common import BaseRouter
from app.auth_config import get_user_manager
from app.logic.auth_processing import handle_registration
from app.schemas.user import UserCreate, UserRead

# router = APIRouter() # Old raw APIRouter
# Standardized router initialization
auth_api_router = APIRouter()  # Create standard APIRouter first
router = BaseRouter(
    router=auth_api_router, default_tags=["auth"]
)  # Wrap with BaseRouter

logger = logging.getLogger(__name__)

register_responses = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorModel,
        "content": {
            "application/json": {
                "examples": {
                    ErrorCode.REGISTER_USER_ALREADY_EXISTS: {
                        "summary": "A user with this email already exists.",
                        "value": {"detail": ErrorCode.REGISTER_USER_ALREADY_EXISTS},
                    },
                    ErrorCode.REGISTER_INVALID_PASSWORD: {
                        "summary": "Password validation failed.",
                        "value": {
                            "detail": {
                                "code": ErrorCode.REGISTER_INVALID_PASSWORD,
                                "reason": "Password should be ...",
                            }
                        },
                    },
                }
            }
        },
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorModel,
        "content": {
            "application/json": {
                "examples": {
                    "server_error": {
                        "summary": "An unexpected server error occurred.",
                        "value": {
                            "detail": "An unexpected error occurred during registration."
                        },
                    }
                }
            }
        },
    },
}


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    name="auth:register",
    responses=register_responses,
)
async def register_request_handler(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """
    Handles the core logic for user registration, delegated from the route handler.
    Relies on @handle_route_errors decorator (via BaseRouter) for exception handling.
    """
    logger.debug(f"Handling registration for email: {request_data.email}")
    result = await handle_registration(
        request_data=request_data, request=request, user_manager=user_manager
    )
    return result
