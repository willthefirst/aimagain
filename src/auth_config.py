import uuid
from typing import Optional

from fastapi import Depends, Request, Response
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase

from src.db import get_user_db
from src.domain.models import User
from src.framework.config import settings
from src.framework.observability import observability


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.SECRET
    verification_token_secret = settings.SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        """Trigger the verify-email flow on new-account creation.

        In development, the user is auto-verified — local dev creates
        throw-away accounts and shouldn't have to click an email link
        just to skip the nag banner (also lets Playwright/MCP automation
        register users without intercepting the verify email). In any
        other environment, call `self.request_verify(user, request)`
        which generates a token and triggers `on_after_request_verify`
        to send the email.

        Wrapped in try/except because email delivery failures must not
        block registration — the user is already created at this point;
        they can re-request the verify link from the nag banner.
        """
        if settings.ENVIRONMENT == "development":
            await self.user_db.update(user, {"is_verified": True})
            return

        try:
            await self.request_verify(user, request)
        except Exception:
            # `request_verify` raises on already-verified or inactive
            # users — neither possible right after register, but the
            # broader catch covers transport failures too. The user can
            # retry via the nag banner's re-send form.
            pass

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Send the password-reset email.

        Lazy-imported so the framework layer can be exercised in
        isolation without loading domain modules. Domain wrapper owns
        link construction + template rendering — single home for the
        URL shape (`src/domain/logic/auth/emails.py`)."""
        from src.domain.logic.auth.emails import send_password_reset_email

        await send_password_reset_email(user, token)

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Send the verify-your-email message.

        Called by fastapi-users when:
          - `on_after_register` triggers `self.request_verify` (the
            new-account flow), or
          - the user POSTs `/auth/request-verify-token` (re-send from
            the nag banner).

        Lazy-imported for the same reason as the reset hook below."""
        from src.domain.logic.auth.emails import send_verification_email

        await send_verification_email(user, token)

    async def on_after_login(
        self,
        user: User,
        request: Optional[Request] = None,
        response: Optional[Response] = None,
    ):
        print(f"User {user.id} has logged in.")
        # Post-login lands on the "find new clients" home — kept in
        # lockstep with `src/main.py:read_root`'s redirect target.
        redirect_url = "/posts?kind=referral"
        next_url = request.query_params.get("next")
        if next_url:
            # Security check: only allow relative URLs that start with "/"
            # and don't start with "//" (which could be protocol-relative URLs to external sites)
            if next_url.startswith("/") and not next_url.startswith("//"):
                # Additional security: ensure it doesn't contain any protocol schemes
                if "://" not in next_url:
                    redirect_url = next_url
        response.status_code = 302
        response.headers["Location"] = redirect_url


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)


transport = CookieTransport()


def get_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.SECRET,
        lifetime_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=transport,
    get_strategy=get_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Raw fastapi-users deps. We wrap them below so every successful resolve
# tags the observability scope — see `src/framework/observability/` for
# why we tag here (inside the request) rather than in middleware (which
# runs after `call_next` and so misses exceptions raised in the handler).
_current_active_user = fastapi_users.current_user(active=True)
_current_admin_user = fastapi_users.current_user(active=True, superuser=True)
_current_optional_user = fastapi_users.current_user(optional=True)


async def current_active_user(user: User = Depends(_current_active_user)) -> User:
    observability.set_user(str(user.id), user.email)
    return user


async def current_admin_user(user: User = Depends(_current_admin_user)) -> User:
    observability.set_user(str(user.id), user.email)
    return user


async def current_optional_user(
    user: Optional[User] = Depends(_current_optional_user),
) -> Optional[User]:
    """Anonymous-allowed variant. Tags the scope only when a user is
    present so anonymous traffic doesn't carry stale identities."""
    if user is not None:
        observability.set_user(str(user.id), user.email)
    return user
