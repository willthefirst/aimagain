"""Dev-only auto-login routes.

Two routes, both only mounted when ``settings.ENVIRONMENT == "development"``:

``GET /dev/login-as-seed-user``
    Logs in as the server-configured ``DEV_LOGIN_EMAIL`` (defaults to
    ``admin@example.com``). No user input accepted — useful as a
    bookmark or first Playwright MCP call.

``GET /dev/login-as?email=<addr>``
    Logs in as any user by email. The email comes from a query param
    (selected from the quick-sign-in dropdown on the login page) rather
    than from server config. Still dev-only — the route 404s outside
    ``ENVIRONMENT=development`` — so it can't be used in production.

Security guards (defense in depth — both must pass for each route):

  1. The router is only mounted when ``settings.ENVIRONMENT ==
     "development"`` — see :func:`mount_dev_routes`. In production
     neither route exists and both 404 without reaching this module.
  2. Each handler raises 404 at request time if ``settings.ENVIRONMENT``
     has somehow drifted. Belt-and-suspenders against a future code path
     that toggles the env flag after app boot.

``DEV_SEED_USERS`` is the canonical list surfaced in the login-page
dropdown. It mirrors the anchor rows in
``scripts/dev/seed/overrides/users.py``.

Tested in ``test_dev_auth.py`` (colocated route tests).
"""

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi_users.manager import BaseUserManager

from src.auth_config import auth_backend, get_strategy, get_user_manager
from src.domain.models import User
from src.framework.config import settings

router = APIRouter(tags=["dev"])

# Mirrors the anchor rows in scripts/dev/seed/overrides/users.py.
# Shown in the login-page quick-sign-in dropdown when ENVIRONMENT=development.
DEV_SEED_USERS: list[dict[str, str]] = [
    {"email": "admin@example.com", "label": "admin (superuser)"},
    {"email": "alice@example.com", "label": "alice"},
    {"email": "bob@example.com", "label": "bob"},
]


async def _login_response(
    email: str, user_manager: BaseUserManager[User, object]
) -> Response:
    """Fetch user by email and return a 302 response with the session cookie set."""
    try:
        user = await user_manager.get_by_email(email)
    except Exception as exc:  # fastapi-users raises UserNotExists
        raise HTTPException(
            status_code=404,
            detail=(
                f"Seed user not found: {email}. "
                "Run `dev seed` to populate the dev database."
            ),
        ) from exc

    # `auth_backend.login(strategy, user)` builds a Response with the
    # cookie set by CookieTransport. Swap status + Location so the browser
    # lands on `/` carrying the freshly-set cookie; root decides the actual
    # landing page (see `src/main.py:read_root`).
    response = await auth_backend.login(get_strategy(), user)
    response.status_code = 302
    response.headers["Location"] = "/"
    return response


@router.get("/dev/login-as-seed-user")
async def login_as_seed_user(
    user_manager: BaseUserManager[User, object] = Depends(get_user_manager),
) -> Response:
    """Issue a session cookie for the configured seed user and 302 to ``/``."""
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=404)
    return await _login_response(settings.DEV_LOGIN_EMAIL, user_manager)


@router.get("/dev/login-as")
async def login_as(
    email: str,
    user_manager: BaseUserManager[User, object] = Depends(get_user_manager),
) -> Response:
    """Issue a session cookie for any user by email and 302 to ``/``.

    The email comes from the quick-sign-in dropdown on the login page.
    Only reachable in ``ENVIRONMENT=development`` — the route is not
    mounted in production.
    """
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=404)
    return await _login_response(email, user_manager)


def mount_dev_routes(app: FastAPI, *, environment: str) -> None:
    """Mount the dev-only routes on ``app`` iff ``environment`` is
    ``"development"``.

    Called from :mod:`src.main` with ``settings.ENVIRONMENT`` so the
    mount decision happens once, at app boot. Production never sees
    these routes registered. Pulled into a function so the
    ``test_mount_dev_routes_*`` tests can pin the gating behavior
    without monkeypatching the global ``app`` instance.
    """
    if environment == "development":
        app.include_router(router)
