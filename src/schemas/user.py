from typing import Literal

from fastapi_users import schemas
from pydantic import BaseModel


class UserRead(schemas.BaseUser):
    username: str


class UserCreate(schemas.BaseUserCreate):
    username: str


class UserUpdate(schemas.BaseUserUpdate):
    username: str


class UserActivationUpdate(BaseModel):
    """Body for `PUT /users/{id}/activation` — sets the user's activation state."""

    state: Literal["active", "deactivated"]
