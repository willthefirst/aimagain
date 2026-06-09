"""Email dispatch — three backends behind one async function.

`send_email` is the only public entry point. The `console` backend is
the default so a fresh checkout sends nothing real; `file` is a
heavier dev option (writes `.eml`-shaped files under `./.mail/` for
HTML inspection); `resend` is the production transport.

Provider-shaped (not Resend-shaped) on purpose — swapping providers
later is a single `_send_resend` rewrite, not a touch every caller.
Higher-level callers like `domain/logic/auth/emails.py` own templating
+ link construction; this layer is pure transport.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.framework.config import settings

EmailBackend = Literal["console", "file", "resend"]


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
) -> None:
    """Send a transactional email via the configured backend.

    Both `html` and `text` parts are required — text/plain is what keeps
    the spam score down at deliverability-strict providers. Callers
    render both from the same template pair (see
    `domain/templates/emails/`).

    `reply_to` is the optional address a recipient's "Reply" goes to
    when it differs from the sending `EMAIL_FROM` address (e.g. an
    in-app message-the-poster flow where the conversation should
    continue between the two real users, not loop back to a no-reply
    mailbox). Omit it for the common case where replies should bounce
    or land in `EMAIL_FROM`'s inbox.

    Errors propagate. Email send is best-effort by design — fastapi-users
    hooks don't expose a retry surface and adding one would be the wrong
    layer. If a provider call fails, the user sees a generic error; they
    can re-request the email via the standard re-send route.
    """
    backend: EmailBackend = settings.EMAIL_BACKEND  # type: ignore[assignment]

    if backend == "console":
        _send_console(to=to, subject=subject, html=html, text=text, reply_to=reply_to)
    elif backend == "file":
        _send_file(to=to, subject=subject, html=html, text=text, reply_to=reply_to)
    elif backend == "resend":
        await _send_resend(
            to=to, subject=subject, html=html, text=text, reply_to=reply_to
        )
    else:
        raise ValueError(
            f"Unknown EMAIL_BACKEND={backend!r}; expected one of "
            "'console', 'file', 'resend'"
        )


def _send_console(
    *, to: str, subject: str, html: str, text: str, reply_to: str | None
) -> None:
    print("=" * 60, file=sys.stderr)
    print(f"[email:console] To: {to}", file=sys.stderr)
    print(f"[email:console] From: {settings.EMAIL_FROM}", file=sys.stderr)
    if reply_to is not None:
        print(f"[email:console] Reply-To: {reply_to}", file=sys.stderr)
    print(f"[email:console] Subject: {subject}", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(text, file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def _send_file(
    *, to: str, subject: str, html: str, text: str, reply_to: str | None
) -> None:
    out_dir = Path(".mail")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Sanitize subject for the filename — keep ASCII letters/digits/`-`/`_`,
    # collapse runs, cap length. Avoids surprises on Windows-friendly checkouts.
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", subject).strip("-")[:50] or "email"
    path = out_dir / f"{ts}-{slug}.eml"
    reply_to_header = f"Reply-To: {reply_to}\n" if reply_to is not None else ""
    body = (
        f"To: {to}\n"
        f"From: {settings.EMAIL_FROM}\n"
        f"{reply_to_header}"
        f"Subject: {subject}\n"
        f"Content-Type: multipart/alternative\n"
        f"\n"
        f"--text--\n{text}\n"
        f"--html--\n{html}\n"
    )
    path.write_text(body, encoding="utf-8")


async def _send_resend(
    *, to: str, subject: str, html: str, text: str, reply_to: str | None
) -> None:
    """Resend HTTP API call.

    Imported lazily so the `resend` package is only required when this
    backend is actually selected — keeps the console default zero-dep
    in case anyone strips `[app]` extras.
    """
    if not settings.RESEND_API_KEY:
        raise RuntimeError(
            "EMAIL_BACKEND=resend but RESEND_API_KEY is not set. "
            "Set the env var or switch to EMAIL_BACKEND=console."
        )

    import resend  # type: ignore[import-untyped]

    resend.api_key = settings.RESEND_API_KEY
    # Resend's send() is sync; running it in the default thread pool
    # keeps the caller async without pulling in an async HTTP client.
    import asyncio

    payload: dict[str, object] = {
        "from": settings.EMAIL_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to is not None:
        # Resend accepts `reply_to` as a string or list-of-strings; pass
        # the single address as a string to match what we accept on the
        # public surface (one reply target per send, not a list).
        payload["reply_to"] = reply_to

    await asyncio.to_thread(resend.Emails.send, payload)
