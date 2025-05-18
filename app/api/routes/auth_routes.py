import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions, models
from fastapi_users.manager import BaseUserManager
from fastapi_users.router.common import ErrorCode, ErrorModel

from app.auth_config import get_user_manager
from app.logic.auth_processing import handle_registration
from app.schemas.user import UserCreate, UserRead

router = APIRouter()
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
    """
    logger.debug(f"Handling registration for email: {request_data.email}")
    try:
        result = await handle_registration(
            request_data=request_data, request=request, user_manager=user_manager
        )
        logger.debug("Register request handler returning result from handler.")
        return result
    except exceptions.UserAlreadyExists:
        logger.warning(
            f"Registration failed: User already exists - {request_data.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.REGISTER_USER_ALREADY_EXISTS,
        )
    except exceptions.InvalidPasswordException as e:
        logger.warning(f"Registration failed: Invalid password - {request_data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": ErrorCode.REGISTER_INVALID_PASSWORD,
                "reason": e.reason,
            },
        )
    except Exception as e:
        logger.error(
            f"Unexpected error during registration handling: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during registration.",
        )
