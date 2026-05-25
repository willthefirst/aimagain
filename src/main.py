import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from src.auth_config import auth_backend, current_optional_user, fastapi_users
from src.db import check_database_health, get_db_session
from src.domain import routes  # noqa: F401  # populates entity_registry
from src.domain import template_globals  # noqa: F401  # populates Jinja env globals
from src.domain.logic.users.schema import UserRead
from src.domain.models.enums import ONBOARDING_INTENTS
from src.domain.routes import auth_pages, auth_routes, dev_auth, verifications, welcome
from src.framework.config import settings
from src.framework.dispatch.registry import entity_registry
from src.framework.http.middleware import StripEmptyQueryParamsMiddleware
from src.framework.http.responses import APIResponse
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
        # PROVIDER_TEST_MODE manages tables separately, so skip the check.
        skip_table_check = os.getenv("PROVIDER_TEST_MODE") == "true"
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

# Session middleware for pre-auth state (e.g. onboarding intent captured
# on the landing page before the user registers). Uses `SECRET` as the
# session signing key — the same secret used for JWT and password-reset
# tokens. `https_only` follows ENVIRONMENT so local dev works over http.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET,
    https_only=(settings.ENVIRONMENT != "development"),
)


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
async def read_root(
    request: Request,
    user=Depends(current_optional_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Public landing — intent picker for new visitors.

    Returner skip rule: authed users who have already set an intent AND
    own at least one clinician with a `verified` Verification skip the
    picker and land directly on `/openings`. All other authed users see
    the intent picker so they can (re-)confirm their reason for being
    here. Anonymous visitors see the picker and are routed to register
    after picking.
    """
    user_has_verified_clinician = False

    if user is not None and user.onboarding_intent is not None:
        from src.domain.logic.providers.repository import ProviderRepository
        from src.domain.logic.verifications.repository import VerificationRepository

        provider_repo = ProviderRepository(db)
        providers = await provider_repo.list_for_user(user.id)
        if providers:
            verif_repo = VerificationRepository(db)
            for provider in providers:
                latest = await verif_repo.latest_for_provider(provider.id)
                if latest and latest.status == "verified":
                    user_has_verified_clinician = True
                    return RedirectResponse(url="/openings", status_code=302)

    return APIResponse.html_response(
        template_name="landing.html",
        context={
            "user": user,
            "user_has_verified_clinician": user_has_verified_clinician,
        },
        request=request,
    )


@app.post("/onboarding-intent-pending")
async def set_pending_onboarding_intent(
    request: Request,
    intent: str = Form(...),
):
    """Pre-auth intent capture for the landing-page intent picker.

    Writes the selected intent into the session and redirects the visitor
    to `/auth/register`. On successful registration, `on_after_register`
    in `auth_config.py` reads the session key and persists it to the new
    user row, then clears the key.

    Unknown intent values are silently ignored (the session key is not
    set) so a browser replaying a stale form with a removed intent token
    lands on register without crashing.
    """
    if intent in ONBOARDING_INTENTS:
        request.session["onboarding_intent"] = intent
    return RedirectResponse(url="/auth/register", status_code=302)


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
app.include_router(welcome.welcome_api_router)

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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}
