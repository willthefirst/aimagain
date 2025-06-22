from fastapi_users import schemas


class UserRead(schemas.BaseUser):
    username: str


class UserCreate(schemas.BaseUserCreate):
    username: str


class UserUpdate(schemas.BaseUserUpdate):
    username: str
