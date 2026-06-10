from fastapi import APIRouter, Body, Depends, Form, Request
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions as fa_users_exceptions
from fastapi_users import models
from fastapi_users.authentication import Strategy
from fastapi_users.manager import BaseUserManager
from pydantic import BaseModel, EmailStr, ValidationError

from src.auth_config import auth_backend, current_active_user, get_user_manager
from src.domain.models import User
from src.domain.routes.dev_auth import DEV_SEED_USERS
from src.framework import APIResponse, BaseRouter
from src.framework.config import settings
from src.framework.http.form_error_handler import form_error_handler
from src.framework.http.form_error_registry import register_form_error


class _LoginBadCredentials(Exception):
    """Sentinel raised by `post_login` when authenticate returns None
    or the user is inactive.

    Caught by the route's `@form_error_handler` → `catches=` lookup
    which resolves through `FormErrorRegistry` (registration below) —
    re-renders the login form fragment with the canonical
    "Invalid email or password." banner.

    Deliberately does NOT distinguish between "no such user" and "wrong
    password" — exposing the difference would let an attacker
    enumerate registered emails. The banner copy is the same in either
    case, pinned by `test_post_login_wrapper_nonexistent_user_uses_same_banner`.

    Kept module-private (underscore prefix) — this is the wire between
    the route body and its decorator, not a domain concept.
    """


# Register `_LoginBadCredentials` next to its definition (the
# "register-where-you-define" pattern). Tying the registration to the
# import of this module means the route's `catches=` lookup always
# finds it without a global-side-effect-on-app-boot detour. Domain
# layers that add their own typed exceptions should follow the same
# pattern.
register_form_error(
    _LoginBadCredentials,
    status_code=401,  # RFC 9110 §15.5.2 Unauthorized — bad credentials.
    banner=True,
    message="Invalid email or password.",
)


# Standardized router initialization
auth_pages_api_router = APIRouter(prefix="/auth")
router = BaseRouter(router=auth_pages_api_router, default_tags=["Auth Pages"])


@router.get("/register", name="auth_pages:register")
async def get_register_page(request: Request):
    """Serves the HTML registration page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    return APIResponse.html_response(
        template_name="auth/register.html", context={}, request=request
    )


@router.get("/login", name="auth_pages:login")
async def get_login_page(request: Request):
    """Serves the HTML login page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    next_url = request.query_params.get("next", "")
    # Show a contextual message when arriving from the registration flow
    just_registered = request.query_params.get("registered") == "1"
    dev_users = DEV_SEED_USERS if settings.ENVIRONMENT == "development" else None
    return APIResponse.html_response(
        template_name="auth/login.html",
        context={
            "next_url": next_url,
            "just_registered": just_registered,
            "dev_users": dev_users,
        },
        request=request,
    )


@router.post("/login", name="auth_pages:post_login")
@form_error_handler(
    # Login is browser-only — programmatic clients use `/auth/jwt/login`
    # (which keeps its JSON 400 contract). `require_htmx=False` makes
    # the rerender path fire on every client of *this* route, matching
    # the behavior the route had before the decorator extraction
    # (pinned by `test_post_login_wrapper_nonexistent_user_uses_same_banner`,
    # which posts without an `HX-Request` header and expects the
    # banner in the response).
    #
    # Banner-only, no field error: deliberately doesn't tell the user
    # whether the username or the password was wrong — distinguishing
    # would let an attacker enumerate registered emails.
    template="auth/_login_form.html",
    # `prefill_fields` omitted → auto-detect from the submitted
    # `OAuth2PasswordRequestForm`. `username` is prefilled; `password`
    # is dropped by the sensitive-field denylist. (`scope`,
    # `client_id`, `client_secret` get prefilled too — harmless for
    # this form, and matches what a non-magical reader of the
    # OAuth2-form spec would expect.)
    catches=(_LoginBadCredentials,),
    context_builder=lambda kwargs: {
        "next_url": kwargs["request"].query_params.get("next", "")
    },
    require_htmx=False,
)
async def post_login(
    request: Request,
    credentials: OAuth2PasswordRequestForm = Depends(),
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    strategy: Strategy[models.UP, models.ID] = Depends(auth_backend.get_strategy),
):
    """HTMX-friendly login that wraps fastapi-users' `auth_backend.login`.

    fastapi-users' built-in `/auth/jwt/login` handler returns a JSON 400
    on bad credentials, which HTMX has nowhere to land — the user sees
    nothing. This route exists to surface the failure inline:

      - bad credentials / inactive user → raise `_LoginBadCredentials`;
        the `@form_error_handler` decorator catches it and re-renders
        the form fragment with the banner (`form_values["username"]`
        prefills the email so the user only retypes the password;
        password is intentionally never echoed back into HTML).
      - success → mint the cookie exactly as fastapi-users' login
        does (delegate to `auth_backend.login`) and add `HX-Redirect`
        pointing at `?next=` (or `/` if absent) so HTMX navigates
        instead of trying to swap a 204-no-body response.

    The original `/auth/jwt/login` route stays mounted (third-party
    OAuth flows, programmatic clients, contract tests) — this is
    purely the form-handler addition for the browser flow.

    Templates that opt into the form-error rerender pattern must
    import their form-fields / form-banner macros `with context` so
    the auto-resolution from `form_errors` / `form_banner_text` lands;
    see `src/framework/http/form_rerender.py`.
    """
    next_url = request.query_params.get("next", "") or "/"
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise _LoginBadCredentials()
    response = await auth_backend.login(strategy, user)
    # `UserManager.on_after_login` mutates the response into a 302 +
    # `Location` (see `src/auth_config.py`) — that's the right shape
    # for plain browser POSTs. For HTMX, however, an auto-followed 302
    # would land HTML from the redirect target into the form-swap
    # slot, not the intended page navigation. The branch below
    # converts to 204 + `HX-Redirect` for HTMX so HTMX honors the
    # navigation explicitly. Non-HTMX clients (contract tests,
    # third-party tools) keep the existing 302 contract.
    await user_manager.on_after_login(user, request, response)
    if request.headers.get("HX-Request") == "true":
        # Starlette's `MutableHeaders` lacks `.pop`; use the explicit
        # get-then-delete pattern so the underlying multi-value header
        # collection stays consistent.
        location = response.headers.get("Location", next_url)
        if "Location" in response.headers:
            del response.headers["Location"]
        response.headers["HX-Redirect"] = location
        response.status_code = 204
    return response


@router.get("/forgot-password", name="auth_pages:forgot_password")
async def get_forgot_password_page(request: Request):
    """Serves the HTML forgot password page.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page.
    """
    return APIResponse.html_response(
        template_name="auth/forgot_password.html", context={}, request=request
    )


class _ForgotPasswordRequest(BaseModel):
    """Request body for the HTMX-friendly forgot-password wrapper.

    Matches the JSON shape fastapi-users' built-in `POST
    /auth/forgot-password` expects (`{"email": "..."}`). `EmailStr`
    handles malformed-email validation so the wrapper can raise a
    `RequestValidationError` and let the decorator render the inline
    error on the email input.
    """

    email: EmailStr


class _MalformedForgotPasswordBody(Exception):
    """Sentinel raised when the JSON body fails `_ForgotPasswordRequest`
    validation inside the route body (not via FastAPI auto-validation —
    that fires before the decorator can catch it).

    Carries the Pydantic-style errors list so the registered handler
    can build a `{field: msg}` dict via `build_form_errors_dict`.
    """

    def __init__(self, errors: list[dict]):
        self.errors = errors


def _render_validation_errors(exc: _MalformedForgotPasswordBody) -> "FormError":
    """Convert collected validation errors to a `FormError`.

    Reuses `build_form_errors_dict` (the same helper `mount_create`
    uses on a Pydantic 422 path) so the loc-to-field mapping is
    shared.
    """
    from src.framework.dispatch.mounts.create import build_form_errors_dict
    from src.framework.http.form_error_handler import FormError

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


@router.post("/forgot-password", name="auth_pages:post_forgot_password")
@form_error_handler(
    # Browser-only flow — programmatic clients hit this same path; the
    # wrapper returns 202 for non-HTMX preserving the documented JSON
    # contract (pinned by `test_forgot_password_request*`).
    # `require_htmx=False` so a bare POST with a malformed body also
    # lands on the rerender path.
    #
    # We use a route-private sentinel (`_MalformedForgotPasswordBody`)
    # instead of FastAPI's `RequestValidationError` because the latter
    # is raised by FastAPI's framework machinery *before* the route
    # function runs — outside the decorator's try/except. The route
    # body parses the request manually and raises the sentinel inside
    # the decorated function so the decorator catches it.
    template="auth/_forgot_password_form.html",
    handlers={_MalformedForgotPasswordBody: _render_validation_errors},
    require_htmx=False,
)
async def post_forgot_password(
    request: Request,
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """HTMX-friendly forgot-password wrapper. Same JSON wire shape as
    fastapi-users' built-in but returns rendered HTML for HTMX clients.

    Replaces fastapi-users' router-mounted route at this path
    (registration order in `src/main.py` puts auth_pages first so this
    wrapper wins). Replicates the original behavior:

      - Look up user by email; if found, call
        `user_manager.forgot_password(user, request)` which mints a
        token and triggers `on_after_forgot_password` → send-reset-
        email. Swallow `UserNotExists` and `UserInactive` silently to
        avoid revealing which emails are registered.
      - Return 202 (no body) for non-HTMX clients so the existing
        JSON contract is preserved.
      - For HTMX clients, render the form fragment with a success
        banner ("If an account ..."). Same banner copy whether the
        email exists or not — anti-enumeration.

    Body parsing is manual (not a FastAPI `body:` param) because the
    framework's auto-validation raises `RequestValidationError`
    *before* the route runs — too early for the decorator to catch.
    Parsing inside the body lets the decorator render the inline
    error on the email field.
    """
    try:
        raw = await request.json()
    except Exception:
        raise _MalformedForgotPasswordBody(
            [{"loc": ("email",), "msg": "Body must be JSON.", "type": "value_error"}]
        )
    try:
        body = _ForgotPasswordRequest.model_validate(raw)
    except ValidationError as e:
        raise _MalformedForgotPasswordBody(e.errors())

    try:
        user = await user_manager.get_by_email(body.email)
        await user_manager.forgot_password(user, request)
    except (fa_users_exceptions.UserNotExists, fa_users_exceptions.UserInactive):
        # Anti-enumeration — same response either way.
        pass

    if request.headers.get("HX-Request") == "true":
        return APIResponse.html_response(
            template_name="auth/_forgot_password_form.html",
            context={
                "form_banner_text": (
                    "If an account with that email exists, "
                    "you'll receive a reset link shortly."
                ),
                "form_errors": {},
                "form_values": {"email": body.email},
                "submitted": True,
            },
            request=request,
        )
    # Non-HTMX clients keep the documented JSON 202 contract.
    return Response(status_code=202)


class _ResetPasswordRequest(BaseModel):
    """Request body for the HTMX-friendly reset-password wrapper.

    Matches fastapi-users' built-in shape (`{"token": "...",
    "password": "..."}`). Validation is wired through the same
    sentinel-exception pattern as `post_forgot_password` so the
    decorator can render inline errors — FastAPI's auto-validation
    would raise too early in the request lifecycle.
    """

    token: str
    password: str


class _MalformedResetPasswordBody(Exception):
    """Sentinel raised when the JSON body fails validation inside the
    reset-password route body. See `_MalformedForgotPasswordBody` for
    why we use a custom sentinel instead of `RequestValidationError`.
    """

    def __init__(self, errors: list[dict]):
        self.errors = errors


def _render_reset_password_validation_errors(
    exc: _MalformedResetPasswordBody,
) -> "FormError":
    """Convert collected validation errors to a `FormError`. Same
    plumbing as `_render_validation_errors` for forgot-password —
    `build_form_errors_dict` does the loc-to-field mapping."""
    from src.framework.dispatch.mounts.create import build_form_errors_dict
    from src.framework.http.form_error_handler import FormError

    return FormError(
        field_errors=build_form_errors_dict(exc.errors),
        status_code=422,
    )


@router.post("/reset-password", name="auth_pages:post_reset_password")
@form_error_handler(
    # Browser-only — the form posts via `hx-ext="json-enc"`.
    # Programmatic clients hit the same path; for non-HTMX successful
    # resets we still return 200 with no body (matching fastapi-users'
    # original contract).
    #
    # `InvalidResetPasswordToken` and `InvalidPasswordException` are
    # both registered in `FormErrorRegistry` so `catches=` resolves
    # them. The token-invalid case is a banner (no single input pin);
    # the password-policy case lands on the `password` input.
    #
    # `_MalformedResetPasswordBody` covers Pydantic body-shape failures
    # (missing token, empty password) and goes through `handlers=`
    # because it carries multi-field errors.
    #
    # `body: dict = Body(...)` (below) lets FastAPI bind the raw JSON
    # payload without auto-validation, so the parsed body lands in
    # the route's kwargs. The decorator's auto-prefill (PR #847) then
    # discovers the `token` field and round-trips it into the hidden
    # input on rerender — password is dropped by the sensitive-field
    # denylist.
    template="auth/_reset_password_form.html",
    catches=(
        fa_users_exceptions.InvalidResetPasswordToken,
        fa_users_exceptions.InvalidPasswordException,
    ),
    handlers={_MalformedResetPasswordBody: _render_reset_password_validation_errors},
    require_htmx=False,
)
async def post_reset_password(
    request: Request,
    body: dict = Body(...),
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """HTMX-friendly reset-password wrapper. Same JSON wire shape as
    fastapi-users' built-in but returns rendered HTML for HTMX clients
    on every failure mode.

    Failure modes:
      - Malformed body → `_MalformedResetPasswordBody` → 422 + per-field
        errors (`token`/`password` whichever failed).
      - Invalid / expired token → `InvalidResetPasswordToken` → 410 +
        banner ("This reset link is invalid or has expired.").
      - Password policy → `InvalidPasswordException` → 422 + inline
        error on `password` input via the registry.

    On success: 200 with a confirmation banner. Browsers can then
    follow the "Log in" link in the page footer; programmatic clients
    get the same 200 with empty body that fastapi-users emits.

    `body: dict = Body(...)` accepts the raw JSON without Pydantic
    validation (which would raise `RequestValidationError` outside
    the decorator's reach). Validation happens manually below; the
    raw dict in kwargs is what the auto-prefill path uses to keep
    the `token` field across a rerender (password is dropped by the
    sensitive-field denylist).
    """
    try:
        parsed = _ResetPasswordRequest.model_validate(body)
    except ValidationError as e:
        raise _MalformedResetPasswordBody(e.errors())

    await user_manager.reset_password(parsed.token, parsed.password, request)

    if request.headers.get("HX-Request") == "true":
        return APIResponse.html_response(
            template_name="auth/_reset_password_form.html",
            context={
                "token": parsed.token,
                "form_banner_text": (
                    "Password updated. You can now log in with your new password."
                ),
                "form_errors": {},
                "form_values": {},
                "reset_complete": True,
            },
            request=request,
        )
    return Response(status_code=200)


@router.get("/reset-password/{token}", name="auth_pages:reset_password")
async def get_reset_password_page(request: Request, token: str):
    """Serves the HTML reset password page, including the token.

    Args:
        request: The FastAPI request object.
        token: The password reset token from the URL path.

    This endpoint is automatically logged and error-handled by the BaseRouter decorators.

    Returns:
        TemplateResponse: The rendered HTML page with the token in context.
    """
    return APIResponse.html_response(
        template_name="auth/reset_password.html",
        context={"token": token},
        request=request,
    )


@router.get("/verify", name="auth_pages:verify")
async def get_verify_page(request: Request):
    """Render the "click to verify" confirm page.

    The email contains `GET /auth/verify?token=...`. The GET handler
    deliberately does NOT consume the token — it just renders a page
    with a button that POSTs to the sibling handler. Two reasons:

      - Link prefetchers (corporate AV, Outlook Safe Links, Gmail
        preview crawlers) issue GETs against email URLs and would burn
        the token before the user clicks. POST sidesteps every one of
        them.
      - GET is supposed to be safe / idempotent. Mutating user state
        on GET is the kind of accident that makes auditors itch.

    Token validation (expired, malformed, already used) happens at POST
    time — keeps the GET path stateless and the GET response cacheable.
    Missing `?token=` is the one case GET catches: a broken URL renders
    the error state immediately instead of a confirm button that's
    guaranteed to fail.
    """
    token = request.query_params.get("token", "")
    return APIResponse.html_response(
        template_name="auth/verify.html",
        context={"token": token, "status": "error" if not token else None},
        request=request,
    )


@router.post("/verify", name="auth_pages:post_verify")
async def post_verify(
    request: Request,
    token: str = Form(""),
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
    strategy: Strategy[models.UP, models.ID] = Depends(auth_backend.get_strategy),
):
    """Consume the verify token, auto-login on success, redirect to /.

    Sole mutation point for the verify flow — GET just hosts the
    button. Three outcomes:

      - Success → mint the session cookie via `auth_backend.login`
        (same path `/auth/login` uses); HX-Redirect (or 302 + Location
        for non-HTMX) to the post-login home, mirroring `post_login`'s
        HTMX-vs-browser branch. The user is logged in by the response
        the browser hands back.
      - `UserAlreadyVerified` → render the `already_verified` state
        with a login link. Deliberately NOT auto-login — a second
        click against an already-consumed token could be from a leaked
        post-use URL (browser history on a shared machine, log
        scraping, etc.), and convenience here is not worth the risk.
      - Missing token, `InvalidVerifyToken`, `UserNotExists` → render
        the error state.
    """
    if not token:
        return APIResponse.html_response(
            template_name="auth/verify.html",
            context={"token": "", "status": "error"},
            request=request,
        )
    try:
        user = await user_manager.verify(token, request)
    except fa_users_exceptions.UserAlreadyVerified:
        return APIResponse.html_response(
            template_name="auth/verify.html",
            context={"token": "", "status": "already_verified"},
            request=request,
        )
    except (
        fa_users_exceptions.InvalidVerifyToken,
        fa_users_exceptions.UserNotExists,
    ):
        return APIResponse.html_response(
            template_name="auth/verify.html",
            context={"token": "", "status": "error"},
            request=request,
        )

    # Success: mint the cookie + redirect, same dual-mode shape as
    # post_login (HTMX → 204 + HX-Redirect; plain browser POST → 302
    # + Location). Cookie is preserved on either branch — it's set
    # by the response `auth_backend.login` returns, which we mutate
    # in place rather than replace.
    #
    # Destination is the clinician-create form, NOT `on_after_login`'s
    # default (/posts?kind=referral). #1302 routes verify-success into
    # the create-clinician funnel — the intended next step for a
    # freshly-verified new user — and that intent persists across the
    # GET-render / POST-confirm split.
    from src.framework.rendering.route_urls import entity_form_url

    next_url = entity_form_url("clinician")
    response = await auth_backend.login(strategy, user)
    if request.headers.get("HX-Request") == "true":
        response.headers["HX-Redirect"] = next_url
        response.status_code = 204
    else:
        response.headers["Location"] = next_url
        response.status_code = 302
    return response


@router.post("/resend-verify", name="auth_pages:resend_verify")
async def post_resend_verify(
    request: Request,
    current_user: User = Depends(current_active_user),
    user_manager: BaseUserManager[models.UP, models.ID] = Depends(get_user_manager),
):
    """Re-send the verify email for the currently-authed user.

    Sits in front of fastapi-users' `POST /auth/request-verify-token`
    so the nag banner doesn't need to expose the user's email in HTML
    (and doesn't need a JSON-encoding HTMX form). Reads the user from
    the session cookie; calls `request_verify` which triggers
    `on_after_request_verify` → `send_verification_email`.

    Returns `HX-Redirect: /users/me/email/form?sent=1` so the user lands
    on the consolidated email-management / CTA page with a "just sent
    another email" status — same UX surface as the post-registration flow.
    """
    try:
        await user_manager.request_verify(current_user, request)
    except fa_users_exceptions.UserAlreadyVerified:
        # Edge case: user verified in another tab between page load
        # and the resend click. The CTA page is harmless either way —
        # let it render and the nag goes away on next reload.
        pass
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/users/me/email/form?sent=1"
    return response


@router.post("/sign-out", name="auth_pages:sign_out")
async def post_sign_out(request: Request):
    """Clear the session cookie and redirect to the login page (#702).

    Deletes the `fastapiusersauth` cookie (CookieTransport default name)
    and sends `HX-Redirect` so HTMX does a full navigation — the chrome
    immediately reflects the anonymous state without a stale header.
    """
    response = Response(status_code=200)
    response.delete_cookie("fastapiusersauth")
    response.headers["HX-Redirect"] = "/auth/login"
    return response
