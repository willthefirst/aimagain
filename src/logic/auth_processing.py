# src/logic/auth_processing.py
import logging

from fastapi import Depends, Request
from fastapi_users import models
from fastapi_users.manager import BaseUserManager, UserManagerDependency

from src.auth_config import get_user_manager
from src.schemas.user import UserCreate, UserRead

logger = logging.getLogger(__name__)

AppUserManager = UserManagerDependency[models.UP, models.ID]


async def handle_registration(
    request_data: UserCreate,
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
) -> UserRead:
    created_user = await user_manager.create(request_data, safe=True, request=request)
    return created_user
