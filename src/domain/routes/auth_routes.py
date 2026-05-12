import logging

from fastapi import APIRouter, Depends, Request, status
from fastapi_users import models
from fastapi_users.manager import BaseUserManager
from fastapi_users.router.common import ErrorCode, ErrorModel

from src.auth_config import get_user_manager
from src.domain.logic.auth.handlers import handle_registration
from src.domain.logic.users.schema import UserCreate, UserRead
from src.framework import BaseRouter
from src.framework.audit.repository import AuditRepository
from src.framework.persistence.dependencies import get_audit_repository

auth_api_router = APIRouter()
router = BaseRouter(router=auth_api_router, default_tags=["auth"])

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
    audit_repo: AuditRepository = Depends(get_audit_repository),
):
    logger.debug(f"Handling registration for email: {request_data.email}")
    result = await handle_registration(
        request_data=request_data,
        request=request,
        user_manager=user_manager,
        audit_repo=audit_repo,
    )
    return result
