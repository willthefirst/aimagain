import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.auth_config import (
    auth_backend,
    current_optional_user,
    fastapi_users,
)
from src.db import check_database_health
from src.domain import routes  # noqa: F401  # populates entity_registry
from src.domain import template_globals  # noqa: F401  # populates Jinja env globals
from src.domain.logic.users.schema import UserRead
from src.domain.routes import (
    access,
    auth_pages,
    auth_routes,
    dev_auth,
    dev_components,
    user_email,
    verifications,
)
from src.framework.config import settings
from src.framework.dispatch.registry import entity_registry
from src.framework.http.middleware import (
    StaticLongCacheMiddleware,
    StaticNoCacheMiddleware,
    StripEmptyQueryParamsMiddleware,
)
from src.framework.http.responses import APIResponse
from src.framework.http.static_files import MinifyingStaticFiles
from src.framework.observability import observability
from src.jobs.scheduler import make_scheduler, register_jobs

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
        # CLINICIAN_TEST_MODE manages tables separately, so skip the check.
        skip_table_check = os.getenv("CLINICIAN_TEST_MODE") == "true"
        await check_database_health(skip_table_check=skip_table_check)
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        logger.error("Application startup aborted due to database issues")
        raise

    # APScheduler runs inside the app process so jobs share the real
    # async_session_maker and audit repository (see src/jobs/README.md).
    # DISABLE_SCHEDULER=1 skips the subsystem entirely (dev + pytest); job
    # registration is exercised by src/jobs/test_scheduler.py instead.
    if os.getenv("DISABLE_SCHEDULER") == "1":
        scheduler = None
    else:
        scheduler = make_scheduler()
        register_jobs(scheduler)
        scheduler.start()
        logger.info("APScheduler started")

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Bedlam Connect", lifespan=lifespan)

# Initialize the error tracking / tracing provider. No-op when no DSN
# is configured — see `src/framework/observability/` for the contract
# and how to swap providers.
observability.init_app(app)

# Strip empty query-string pairs at request entry so HTML-form
# submissions ("Apply" with no filter selected → `?x=`) behave the same
# as omitting the param. See `src/framework/http/middleware.py` for the
# full convention rationale.
app.add_middleware(StripEmptyQueryParamsMiddleware)

if settings.ENVIRONMENT == "development":
    app.add_middleware(StaticNoCacheMiddleware)
else:
    # Production / staging — emit far-future cache headers on versioned
    # asset URLs and a short revalidating TTL on the rest. See the
    # middleware docstring for the URL convention.
    app.add_middleware(StaticLongCacheMiddleware)
    # Compress HTML + CSS + JSON over the wire. `minimum_size=500`
    # skips tiny responses where the gzip header itself would bloat
    # the payload. Same content + smaller transfer = lower TTFB on
    # every page, especially first-paint CSS (Lighthouse:
    # "render-blocking" insight). Dev is skipped — the LiveReload
    # snippet relies on bare HTTP/1.1 chunked frames.
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=500)


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


async def _root_response(request: Request, user) -> RedirectResponse | APIResponse:
    # Authenticated users land on the unified `/posts` browse feed — the
    # default landing surface (mock §3). Browse lists every kind newest-first
    # and carries the Referrals/Openings intent toggle + filter rail, so the
    # old `/home` dashboard (My posts + Recent in the network) is fully folded
    # in: "My posts" is `/posts?owner=me` (nav avatar menu) and "Recent in the
    # network" *is* the default newest-first feed. Anonymous visitors see the
    # public landing page instead of being redirected to the login wall.
    if user is not None:
        return RedirectResponse(url="/posts", status_code=302)
    return APIResponse.html_response(
        template_name="landing.html",
        context={},
        request=request,
    )


@app.get("/")
async def read_root(request: Request, user=Depends(current_optional_user)):
    return await _root_response(request, user)


@app.get("/home")
async def read_home(request: Request, user=Depends(current_optional_user)):
    # `/home` is retained only as an alias of `/` so the anonymous brand
    # link (`_page_header.html`) and any stale bookmark keep resolving:
    # authenticated → `/posts` browse, anonymous → landing. The bespoke
    # dashboard template (`home.html`) was retired in favor of browse.
    return await _root_response(request, user)


app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"]
)

app.include_router(
    auth_routes.auth_api_router,
    prefix="/auth",
    tags=["auth"],
)

# `auth_pages` is included BEFORE `get_reset_password_router()` because
# the latter mounts a `POST /auth/forgot-password` at the same path as
# our HTMX-friendly wrapper. FastAPI matches in registration order, so
# whichever router is included first wins. The fastapi-users routes
# remain mounted (for any path the wrapper doesn't intercept) — see
# `auth_pages.post_forgot_password` for why we wrap.
app.include_router(auth_pages.auth_pages_api_router)
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
app.include_router(verifications.verifications_api_router)
app.include_router(access.access_router)
app.include_router(user_email.user_email_router)

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

# Dev-only routes. Mounted iff `ENVIRONMENT == "development"`; the
# `/dev/login-as-seed-user` shortcut doesn't exist in production. The
# `mount_dev_routes` indirection makes the gating behavior testable
# without monkeypatching the global `app` instance. See
# `src/domain/routes/dev_auth.py` for the full security rationale.
dev_auth.mount_dev_routes(app, environment=settings.ENVIRONMENT)
dev_components.mount_dev_components(app, environment=settings.ENVIRONMENT)

# Static assets. Two mounts keep the framework/domain CSS boundary
# visible at the URL level — framework primitives at /static/fw/,
# site-specific styles at /static/domain/. Both directories are under
# src/ so the files live next to the code they describe.
#
# Production uses `MinifyingStaticFiles` so .css responses go through
# the in-process minifier (~30% byte savings, Lighthouse: "minify-css"
# audit). Dev keeps the bare `StaticFiles` so DevTools shows readable
# source — the no-cache middleware above already prevents the browser
# from stale-caching dev edits.
_StaticFilesCls = (
    StaticFiles if settings.ENVIRONMENT == "development" else MinifyingStaticFiles
)
app.mount(
    "/static/fw", _StaticFilesCls(directory="src/framework/static"), name="static_fw"
)
app.mount(
    "/static/domain",
    _StaticFilesCls(directory="src/domain/static"),
    name="static_domain",
)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
