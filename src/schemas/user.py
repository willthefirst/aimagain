from typing import Literal

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr


class UserRead(schemas.BaseUser):
    username: str


class UserCreate(schemas.BaseUserCreate):
    username: str


class UserUpdate(schemas.BaseUserUpdate):
    username: str


class UserActivationUpdate(BaseModel):
    """Body for `PUT /users/{id}/activation` — sets the user's activation state."""

    state: Literal["active", "deactivated"]


class UserActivationAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for the `/users/{id}/activation`
    state-axis subresource. Captures only the field this mutation can change.
    """

    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class UserAuditSnapshot(BaseModel):
    """Audit `before`/`after` projection for full-record user mutations
    (currently only `delete_user` and `register`). The id lives in
    `audit_log.resource_id` already, so it's not duplicated here.
    """

    username: str
    email: EmailStr
    is_active: bool
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)
