# app/logic/auth_processing.py
import logging

from fastapi import Depends, HTTPException, Request, status

# Import necessary components from fastapi-users and app config
from fastapi_users import exceptions, models
from fastapi_users.manager import BaseUserManager, UserManagerDependency
from fastapi_users.router.common import ErrorCode  # Error codes for responses

from app.auth_config import get_user_manager  # The actual dependency needed
from app.schemas.user import UserCreate, UserRead  # Schemas

logger = logging.getLogger(__name__)

# Define the type for the user manager dependency
AppUserManager = UserManagerDependency[models.UP, models.ID]


async def handle_registration(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
) -> UserRead:
    created_user = await user_manager.create(request_data, safe=True, request=request)
    return created_user
