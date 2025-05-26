from fastapi_users import schemas


class UserRead(schemas.BaseUser):
    username: str
    pass


class UserCreate(schemas.BaseUserCreate):
    username: str
    pass


class UserUpdate(schemas.BaseUserUpdate):
    username: str
    pass
