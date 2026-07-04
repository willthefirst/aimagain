"""Anti-bot defense for the public auth forms (register, forgot-password).

Two layered checks, both funnelled through `enforce_antibot(request)`:

  1. **Honeypot** — a hidden form field (`HONEYPOT_FIELD`) that real users
     never see or fill but naive form-scraping bots do. Runs
     unconditionally — no key, no network — and rejects any submission
     where the field is non-empty.
  2. **Cloudflare Turnstile** — a mostly-invisible challenge whose token
     the browser widget injects as `TURNSTILE_TOKEN_FIELD`. Verified
     server-side against Cloudflare's siteverify endpoint. Gated on
     `settings.CAPTCHA_ENABLED` so tests, local dev, and programmatic
     contract clients pass without a real key.

Both failures surface as `BotChallengeFailed`, a sentinel exception in the
same mould as `_LoginBadCredentials` / `_MalformedForgotPasswordBody`: the
route body raises it and its `@form_error_handler` decorator (via the
`catches=` → `FormErrorRegistry` path registered below) re-renders the form
fragment with a form-level banner. This mirrors `auth_pages` exactly — the
check has to run *inside* the route body (not a FastAPI dependency) because
the decorator's try/except only wraps the body, not dependency resolution.

`verify_turnstile` follows the `nppes.py` graceful-degradation contract:
it never raises, and it *fails closed* (returns False on any transport /
parse / non-200 error) — a captcha-service outage rejects rather than
letting bots through, which is the right trade-off for these two forms.

Provider-specific pieces (the siteverify URL, the token field name, the
`success` payload shape) are isolated in `verify_turnstile`; swapping to
hCaptcha touches only this function and the widget markup in
`_shared/antibot.html`.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import Request

from src.framework.config import settings
from src.framework.http.exceptions import BadRequestError
from src.framework.http.form_error_registry import register_form_error

logger = logging.getLogger(__name__)

# The hidden honeypot input's `name`. Deliberately *not* `email`/`name`/
# `url` — browsers autofill those, which would trip the trap for real
# users. `contact_url` reads as a plausible extra field a bot's generic
# form-filler would populate, but no human sees it (the input is rendered
# offscreen + `aria-hidden` by `_shared/antibot.html`).
HONEYPOT_FIELD = "contact_url"

# The field Cloudflare's Turnstile widget injects into the form. json-enc
# serializes it into the JSON body alongside the form's real fields, so no
# extra client wiring is needed.
TURNSTILE_TOKEN_FIELD = "cf-turnstile-response"

HTTP_TIMEOUT_SECONDS = 10.0
_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class BotChallengeFailed(BadRequestError):
    """Raised inside a route body when the honeypot is tripped or the
    Turnstile token fails verification.

    On an HTMX submit, the route's `@form_error_handler` catches it via
    `catches=` → `FormErrorRegistry` (registration below) and re-renders
    the form fragment with the canonical "couldn't verify you're human"
    banner. For a non-HTMX caller on a route that keeps a JSON contract
    (`/auth/register`), the decorator re-raises — and because this is a
    `BadRequestError` (an `HTTPException`), `handle_route_errors` lets it
    bubble to a clean 400 rather than a generic 500. Subclassing the API
    exception is what keeps the fail path off the 500 error-tracking path.

    Deliberately banner-only and vague: never hint *which* check failed,
    so a bot author can't tune around it.
    """

    def __init__(self) -> None:
        super().__init__(detail="Bot challenge failed.")


# Register next to the definition (the repo's "register-where-you-define"
# pattern, mirroring `_LoginBadCredentials` in `auth_pages.py`). A route
# lists `BotChallengeFailed` under `catches=` and the decorator resolves
# the rendering rules from here — no per-route lambda.
register_form_error(
    BotChallengeFailed,
    status_code=400,  # RFC 9110 §15.5.1 Bad Request — the submission is rejected.
    banner=True,
    message="We couldn't verify that you're human. Please try again.",
)


async def verify_turnstile(
    token: str, remoteip: str | None, *, http: httpx.AsyncClient
) -> bool:
    """Verify a Turnstile token against Cloudflare's siteverify endpoint.

    Pure function, `nppes.py`-style: the caller owns the `httpx.AsyncClient`
    lifetime, and this never raises. It *fails closed* — any transport
    error, non-200 status, or non-JSON body returns False (plus a logged
    warning) so a captcha-service hiccup rejects the submission rather
    than letting it through unverified.
    """
    try:
        response = await http.post(
            _SITEVERIFY_URL,
            data={
                "secret": settings.TURNSTILE_SECRET_KEY,
                "response": token,
                **({"remoteip": remoteip} if remoteip else {}),
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        logger.warning("verify_turnstile: request failed: %s", exc)
        return False

    if response.status_code >= 400:
        logger.warning("verify_turnstile: unexpected status %s", response.status_code)
        return False

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("verify_turnstile: non-JSON payload: %s", exc)
        return False

    return payload.get("success") is True


async def enforce_antibot(request: Request) -> None:
    """Run the honeypot + Turnstile checks for a public form submission.

    Call this as the first line of a protected route body (before any
    side effect). Reads the *already-cached* request body — FastAPI has
    parsed it to bind the route's params by the time the body runs, and
    Starlette caches the bytes, so re-reading is free and safe.

    Raises `BotChallengeFailed` when the honeypot is filled or (when
    `CAPTCHA_ENABLED`) the Turnstile token is missing/blank/invalid.
    Returns None on success.
    """
    body = await _read_body(request)

    # Honeypot: always on. A non-empty value means a bot filled a field
    # no human can see.
    if str(body.get(HONEYPOT_FIELD) or "").strip():
        logger.info("enforce_antibot: honeypot tripped")
        raise BotChallengeFailed()

    if not settings.CAPTCHA_ENABLED:
        return

    token = str(body.get(TURNSTILE_TOKEN_FIELD) or "").strip()
    if not token:
        logger.info("enforce_antibot: missing Turnstile token")
        raise BotChallengeFailed()

    remoteip = request.client.host if request.client else None
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        ok = await verify_turnstile(token, remoteip, http=http)
    if not ok:
        raise BotChallengeFailed()


async def _read_body(request: Request) -> dict:
    """Return the submitted fields as a dict, tolerant of parse failures.

    The public auth forms arrive either json-encoded (register,
    forgot-password via `hx-ext="json-enc"`) or form-encoded. Branch on
    the content type; on any parse error return `{}` so the honeypot
    reads empty and the token reads missing — the caller then decides
    (missing token → rejected when captcha is on; empty honeypot →
    passes the honeypot check).
    """
    content_type = request.headers.get("content-type", "")
    try:
        if content_type.startswith("application/json"):
            parsed = await request.json()
            return parsed if isinstance(parsed, dict) else {}
        form = await request.form()
        return dict(form)
    except Exception:  # noqa: BLE001 — any malformed body degrades to empty.
        return {}
