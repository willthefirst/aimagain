from fastapi_users import schemas
from sqlalchemy import String


class UserRead(schemas.BaseUser):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass
