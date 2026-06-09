"""Post-message transactional email — render + send.

Domain-layer wrapper around `src.framework.email.send_email`. Mirrors
`domain/logic/auth/emails.py` for the in-app "message the poster" flow
hung off `POST /posts/{post_id}/message`: a sender writes a body via
the form on the post detail page, we render the
`emails/post_message.{html,txt}` pair, and send it to the post owner
with the sender's email on the `Reply-To:` header so the poster can
respond off-platform.

The route handler in `domain/routes/posts.py` is the only caller —
keeps Jinja rendering and link construction out of the route file and
in one place per email type.
"""

from __future__ import annotations

from src.domain.models import Post, User
from src.framework.config import settings
from src.framework.email import send_email
from src.framework.rendering.templating import templates


def _absolute_url(path: str) -> str:
    """Join `APP_BASE_URL` with a path. Mirrors
    `domain/logic/auth/emails._absolute_url` — kept local rather than
    extracted because the auth helper is private and a second copy is
    cheaper than promoting one helper to a shared module just for two
    callers."""
    base = settings.APP_BASE_URL.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _render(template_name: str, **context: object) -> str:
    template = templates.env.get_template(f"emails/{template_name}")
    return template.render(**context)


async def send_post_message_email(*, post: Post, sender: User, body: str) -> None:
    """Deliver an in-app message to a post owner.

    Recipient: `post.owner.email` (the poster). `Reply-To` is the
    sender's email — the whole point of the flow is to let the poster
    continue the conversation off-platform in their own mail client,
    so their "Reply" must land on the sender, not on `EMAIL_FROM`'s
    no-reply mailbox.

    Sender identity in the body is `sender.username` (display name —
    the email address is in the headers, not duplicated in the body
    prose). The link back to the post lets the poster re-anchor on
    what was being asked about.
    """
    post_url = _absolute_url(f"/posts/{post.id}")
    context = {
        "sender_username": sender.username,
        "sender_email": sender.email,
        "body": body,
        "post_url": post_url,
    }
    await send_email(
        to=post.owner.email,
        subject="New message about your post on Bedlam Connect",
        html=_render("post_message.html", **context),
        text=_render("post_message.txt", **context),
        reply_to=sender.email,
    )
