from fastapi import Depends, FastAPI

# Import the new auth routes
from app.api.routes import auth_routes
from app.auth_config import auth_backend, current_active_user, fastapi_users
from app.models import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

from .api.routes import auth_pages, conversations, me, participants, users

app = FastAPI(title="AIM again")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}


# Include JWT login/logout routes from fastapi-users
app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)

# REMOVE the default fastapi-users registration router
# app.include_router(
#     fastapi_users.get_register_router(UserRead, UserCreate),
#     prefix="/auth",
#     tags=["auth"],
# )

# ADD the custom registration router
app.include_router(
    auth_routes.router,  # Use the router from auth_routes.py
    prefix="/auth",  # Keep the same prefix
    tags=["auth"],  # Keep the same tag
)

# Keep other fastapi-users routers as needed
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
