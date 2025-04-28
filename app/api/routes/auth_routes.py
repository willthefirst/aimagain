# app/api/routes/auth_routes.py
import logging
from fastapi import APIRouter, Depends, status, Request

# Import necessary components from fastapi-users and app config
from fastapi_users import models
from fastapi_users.manager import BaseUserManager
from app.auth_config import get_user_manager

# Import schemas used for request body validation and response model
from app.schemas.user import UserCreate, UserRead

# Import the handler function (the single dependency)
from app.logic.auth_processing import handle_registration

# Import error model definitions for OpenAPI documentation (optional but good practice)
from fastapi_users.router.common import ErrorCode, ErrorModel

router = APIRouter()
logger = logging.getLogger(__name__)

# Define potential error responses for OpenAPI schema
# These match the exceptions handled in handle_registration
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
                                "reason": "Password should be ...",  # Example reason
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
    "/register",  # Define the path relative to the prefix in main.py
    response_model=UserRead,  # Success response structure
    status_code=status.HTTP_201_CREATED,  # Success status code
    tags=["auth"],  # Tag for OpenAPI grouping
    name="auth:register",  # Unique name for the route
    responses=register_responses,  # Document error responses
)
async def register_request_handler(
    # 1. FastAPI validates request body against UserCreate.
    #    Crucially, this expects application/json content type.
    request_data: UserCreate,
    # 2. Pass the raw request object needed by the handler for context.
    request: Request,
    # 3. Inject the user_manager dependency here in the route handler.
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    # Removed the incorrect handler dependency previously:
    # handler=Depends(handle_registration),
):
    """
    Ultra-thin route handler for user registration.
    Validates request body via UserCreate schema and delegates to handle_registration.
    Injects the user_manager dependency needed by the handler.
    """
    print("Register request handler invoked.")
    logger.debug("Register request handler invoked.")
    # Call the handler function directly, passing the validated data, request,
    # AND the explicitly resolved user_manager dependency.
    result = await handle_registration(
        request_data=request_data, request=request, user_manager=user_manager
    )
    logger.debug("Register request handler returning result from handler.")
    return result
