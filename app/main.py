from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import auth_routes
from app.auth_config import auth_backend, fastapi_users
from app.db import get_db_session
from app.middleware.presence import PresenceMiddleware
from app.schemas.user import UserRead, UserUpdate

from .api.routes import auth_pages, conversations, me, participants, users

app = FastAPI(title="AIM again")

# Add presence middleware with session factory
app.add_middleware(PresenceMiddleware, session_factory=get_db_session)


@app.exception_handler(HTTPException)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """
    Custom exception handler for 401 Unauthorized errors.
    Redirects to login page for browser requests, returns JSON for API requests.
    """
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        # Check if the request accepts HTML (browser request)
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header:
            # Redirect to login page for browser requests
            return RedirectResponse(url="/auth/login", status_code=302)

    # For API requests or other status codes, return the original JSON response
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
def read_root():
    return RedirectResponse(url="/users/me/conversations", status_code=302)


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
