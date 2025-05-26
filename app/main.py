from fastapi import FastAPI

from app.api.routes import auth_routes
from app.auth_config import auth_backend, fastapi_users
from app.middleware.presence import PresenceMiddleware
from app.schemas.user import UserRead, UserUpdate

from .api.routes import auth_pages, conversations, me, participants, users

app = FastAPI(title="AIM again")

# Add presence middleware
app.add_middleware(PresenceMiddleware)


@app.get("/")
def read_root():
    return {"message": "Welcome to the Chat App API"}


app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)

app.include_router(
    auth_routes.auth_api_router,
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
app.include_router(auth_pages.auth_pages_api_router)
app.include_router(users.users_api_router, tags=["users"])
app.include_router(conversations.conversations_router_instance, tags=["conversations"])
app.include_router(me.me_router_instance, tags=["me"])
app.include_router(participants.participants_router_instance, tags=["participants"])
