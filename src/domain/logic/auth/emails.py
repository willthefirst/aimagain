"""Auth-flow transactional emails — link construction + render + send.

Domain-layer wrapper around `src.framework.email.send_email`. Owns:

  - URL shape for verify / reset links (so the routes can move without
    the email module knowing about them — single source of truth for
    the link template).
  - Jinja rendering of `src/domain/templates/emails/*.{html,txt}`.

Hooks in `src.auth_config.UserManager` call these — never the
framework's `send_email` directly — so verify/reset link construction
stays in one place. Adding a new transactional email is a new function
here, not a hook-body rewrite.
"""

from __future__ import annotations

from src.domain.models import User
from src.framework.config import settings
from src.framework.email import send_email
from src.framework.rendering.templating import templates


def _absolute_url(path: str) -> str:
    """Join `APP_BASE_URL` with a path. Strip trailing/leading slashes
    to avoid `//` collisions when `APP_BASE_URL` is set with a trailing
    slash in `.env`."""
    base = settings.APP_BASE_URL.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _render(template_name: str, **context: object) -> str:
    """Render one of the email templates to a string. The Jinja env
    is the same one HTTP responses use — keeps autoescape behavior
    consistent (.html files autoescape, .txt files don't, by
    extension)."""
    template = templates.env.get_template(f"emails/{template_name}")
    return template.render(**context)


async def send_password_reset_email(user: User, token: str) -> None:
    """Send the password-reset email.

    `token` is the JWT minted by fastapi-users' reset router; it's
    consumed by `POST /auth/reset-password` (the same router) when
    the user submits the form on `/auth/reset-password/{token}`. Link
    shape must match the GET page route in `auth_pages.py`.
    """
    reset_url = _absolute_url(f"/auth/reset-password/{token}")
    context = {
        "username": user.username,
        "reset_url": reset_url,
    }
    await send_email(
        to=user.email,
        subject="Reset your Bedlam Connect password",
        html=_render("reset_password.html", **context),
        text=_render("reset_password.txt", **context),
    )
