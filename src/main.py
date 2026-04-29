import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from src.api.routes import auth_routes
from src.auth_config import auth_backend, fastapi_users
from src.db import check_database_health
from src.schemas.user import UserRead

from .api.routes import auth_pages, me, posts, users

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class _HealthAccessFilter(logging.Filter):
    """Drop uvicorn access log lines for the /health probe."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return "GET /health " not in message


logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    import os

    # Startup
    try:
        # In provider test mode, skip table check since tables are managed separately
        skip_table_check = os.getenv("PROVIDER_TEST_MODE") == "true"
        await check_database_health(skip_table_check=skip_table_check)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.error("Application startup aborted due to database issues")
        raise

    yield


app = FastAPI(title="Bedlam Connect", lifespan=lifespan)


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
    return RedirectResponse(url="/users", status_code=302)


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
app.include_router(auth_pages.auth_pages_api_router)
# `me` router is registered BEFORE the parametric `/users/{user_id}` routes
# so that `/users/me` matches the literal `me` handler instead of being
# interpreted as a UUID and 422-ing.
app.include_router(me.me_router_instance, tags=["me"])
app.include_router(users.users_api_router, tags=["users"])
app.include_router(posts.posts_api_router, tags=["posts"])


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker and load balancers."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
