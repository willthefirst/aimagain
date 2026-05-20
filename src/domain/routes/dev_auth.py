"""Dev-only auto-login route.

Visiting ``GET /dev/login-as-seed-user`` issues the same session
cookie a production login would (via ``auth_backend.login`` with the
JWT strategy from :mod:`src.auth_config`) for the user named by
``settings.DEV_LOGIN_EMAIL``, then 302s to ``/posts``. Useful in two
places:

  * Manual development — bookmark the URL. One click after starting
    the dev server and you're authenticated; no form to fill.
  * Playwright MCP agent — first tool call of a session navigates here,
    then every subsequent navigate happens with the auth cookie set.

Security guards (defense in depth — both must pass):

  1. The route is only mounted on the FastAPI app when
     ``settings.ENVIRONMENT == "development"`` — see
     :func:`mount_dev_routes`. In production the route doesn't exist
     and 404s without ever reaching this module.
  2. The handler additionally raises 404 if ``settings.ENVIRONMENT``
     somehow drifts out of "development" at request time. Belt-and-
     suspenders against a future code path that toggles the env flag
     after app boot.

The route never accepts user input — the seed-user identifier comes
from the server-side ``DEV_LOGIN_EMAIL`` setting, not from query
params — so it can't be tricked into authenticating as an arbitrary
user. The seed user must already exist in the database; otherwise the
handler 404s.

Tested in `test_dev_auth.py` (the colocated route test).
"""

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import Response
from fastapi_users.manager import BaseUserManager

from src.auth_config import auth_backend, get_strategy, get_user_manager
from src.domain.models import User
from src.framework.config import settings

router = APIRouter(tags=["dev"])


@router.get("/dev/login-as-seed-user")
async def login_as_seed_user(
    user_manager: BaseUserManager[User, object] = Depends(get_user_manager),
) -> Response:
    """Issue a session cookie for the configured seed user and 302 to
    ``/`` — root then decides where to land (see ``read_root`` in
    ``src/main.py``), so this handler doesn't bake in a specific
    resource path."""
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=404)

    try:
        user = await user_manager.get_by_email(settings.DEV_LOGIN_EMAIL)
    except Exception as exc:  # fastapi-users raises UserNotExists
        raise HTTPException(
            status_code=404,
            detail=(
                f"Seed user not found: {settings.DEV_LOGIN_EMAIL}. "
                "Run `dev seed` to populate the dev database."
            ),
        ) from exc

    # `auth_backend.login(strategy, user)` builds a Response with the
    # cookie set by the transport (CookieTransport in our config). We
    # then swap the status + Location header so the agent / browser
    # lands on `/` (which redirects onward) carrying the freshly-set
    # cookie. Routing the landing through `/` keeps the
    # "where does an authenticated session land?" decision in one
    # place — `src/main.py:read_root` — instead of duplicating it here.
    response = await auth_backend.login(get_strategy(), user)
    response.status_code = 302
    response.headers["Location"] = "/"
    return response


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
