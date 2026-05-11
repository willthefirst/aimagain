from typing import Literal

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr

from src.schemas._validators import ReadProjection


class UserRead(schemas.BaseUser):
    username: str


class UserCreate(schemas.BaseUserCreate):
    username: str


class UserUpdate(schemas.BaseUserUpdate):
    username: str


class UserActivationUpdate(BaseModel):
    """Body for `PUT /users/{id}/activation` — sets the user's activation state."""

    state: Literal["active", "deactivated"]


class UserActivationAuditSnapshot(ReadProjection):
    """Audit `before`/`after` projection for the `/users/{id}/activation`
    state-axis subresource. Captures only the field this mutation can change.
    """

    is_active: bool


class UserAuditSnapshot(ReadProjection):
    """Audit `before`/`after` projection for full-record user mutations
    (currently only `delete_user` and `register`). The id lives in
    `audit_log.resource_id` already, so it's not duplicated here.
    """

    username: str
    email: EmailStr
    is_active: bool
    is_superuser: bool
