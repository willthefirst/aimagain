from fastapi import Depends, FastAPI

from app.models import User
from .api.routes import users
from .api.routes import conversations
from .api.routes import me
from .api.routes import participants
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.auth_config import auth_backend, current_active_user, fastapi_users
from .api.routes import auth_pages


app = FastAPI(title="Chat App")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}


app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)
app.include_router(auth_pages.router)
app.include_router(users.router, tags=["users"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(me.router, tags=["me"])
app.include_router(participants.router, tags=["participants"])
