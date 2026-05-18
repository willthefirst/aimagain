import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from src.auth_config import auth_backend, fastapi_users
from src.db import check_database_health
from src.domain import routes  # noqa: F401  # populates entity_registry
from src.domain.logic.users.schema import UserRead
from src.domain.routes import auth_pages, auth_routes
from src.framework.dispatch.registry import entity_registry
from src.framework.http.middleware import StripEmptyQueryParamsMiddleware

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
    import os

    try:
        # PROVIDER_TEST_MODE manages tables separately, so skip the check.
        skip_table_check = os.getenv("PROVIDER_TEST_MODE") == "true"
        await check_database_health(skip_table_check=skip_table_check)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.error("Application startup aborted due to database issues")
        raise

    yield


app = FastAPI(title="Bedlam Connect", lifespan=lifespan)

# Strip empty query-string pairs at request entry so HTML-form
# submissions ("Apply" with no filter selected → `?x=`) behave the same
# as omitting the param. See `src/framework/http/middleware.py` for the
# full convention rationale.
app.add_middleware(StripEmptyQueryParamsMiddleware)


@app.exception_handler(HTTPException)
async def unauthorized_exception_handler(request: Request, exc: HTTPException):
    """Redirect HTML 401s to /auth/login; pass JSON 401s through."""
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header:
            original_url = request.url.path
            return RedirectResponse(
                url=f"/auth/login?next={original_url}", status_code=302
            )

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
def read_root():
    return RedirectResponse(url="/posts", status_code=302)


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

# Every entity route file calls `register_entity(SPEC)` at import time
# (see `src/framework/dispatch/registry.py`). The package import above
# (`from src.domain import routes`) executes those calls. Mounting is
# then a single iteration over `entity_registry` — no `include_router`
# line to forget per entity. Owned-subentity specs mount nested under
# their parent's route file and are not registered here.
# Tags come from each spec's `BaseRouter.default_tags`
# (`register_entity` sets them to `[spec.url_collection]`); no need to
# repeat them on `include_router`.
for _, _router in entity_registry.entries():
    app.include_router(_router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
