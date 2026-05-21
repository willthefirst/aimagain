from typing import Literal

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr, Field

from src.framework.schema_validators import ReadProjection


class UserRead(schemas.BaseUser):
    username: str
    # `is_verified` is inherited from fastapi_users.BaseUser but the app
    # has no verification flow — every account is permanently `False`.
    # Exclude it from the JSON response so we stop advertising a contract
    # we don't honour (#696). The DB column stays; fastapi-users requires
    # it on the ORM model. Remove this override if a verification flow is
    # ever shipped (Option A from #696).
    is_verified: bool = Field(default=False, exclude=True)


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
