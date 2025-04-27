# app/logic/auth_processing.py
import logging
from fastapi import Depends, HTTPException, status, Request

# Import necessary components from fastapi-users and app config
from fastapi_users import exceptions, models
from fastapi_users.manager import BaseUserManager, UserManagerDependency
from app.auth_config import get_user_manager  # The actual dependency needed
from app.schemas.user import UserCreate, UserRead  # Schemas
from fastapi_users.router.common import ErrorCode  # Error codes for responses

logger = logging.getLogger(__name__)

# Define the type for the user manager dependency
AppUserManager = UserManagerDependency[models.UP, models.ID]


async def handle_registration(
    # Data passed from the route handler
    request_data: UserCreate,
    request: Request,
    # Dependency injected here: the user manager
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
) -> UserRead:  # Return type matches the route handler's response_model
    """
    Handles the core logic for user registration, delegated from the route handler.
    """
    logger.debug(f"Handling registration for email: {request_data.email}")

    try:
        # Call the user manager's create method (core business logic)
        created_user = await user_manager.create(
            request_data, safe=True, request=request
        )
        logger.info(f"Successfully created user {created_user.id}")
        # The endpoint's response_model handles Pydantic validation/serialization
        return created_user

    # Handle exceptions specific to fastapi-users registration
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
    # Catch other potential exceptions during user creation
    except Exception as e:
        logger.error(
            f"Unexpected error during registration handling: {e}", exc_info=True
        )
        # Generic error for unexpected issues
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during registration.",
        )
