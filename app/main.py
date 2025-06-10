import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.routes import auth_routes
from app.auth_config import auth_backend, fastapi_users
from app.db import check_database_health, get_db_session
from app.middleware.presence import PresenceMiddleware
from app.schemas.user import UserRead, UserUpdate
from app.services.migration_service import run_migrations

from .api.routes import auth_pages, conversations, me, participants, users

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    import os

    # Startup
    logger.info("Starting application...")
    try:
        # Run migrations first
        await run_migrations()

        # In provider test mode, skip table check since tables are managed separately
        skip_table_check = os.getenv("PROVIDER_TEST_MODE") == "true"
        await check_database_health(skip_table_check=skip_table_check)
        logger.info("Database health check passed - application ready")
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.error("Application startup aborted due to database issues")
        raise

    yield

    # Shutdown (if needed in future)
    logger.info("Application shutting down...")


app = FastAPI(title="AIM again", lifespan=lifespan)


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
            # Redirect to login page for browser requests with original URL as 'next' parameter
            original_url = request.url.path
            return RedirectResponse(
                url=f"/auth/login?next={original_url}", status_code=302
            )

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


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and load balancers."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
