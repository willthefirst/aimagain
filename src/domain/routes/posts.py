from uuid import UUID

from fastapi import Depends, Request
from pydantic import BaseModel, Field, field_validator

from src.auth_config import current_active_user
from src.domain.logic.capabilities import can_access_network
from src.domain.logic.posts.emails import send_post_message_email
from src.domain.logic.posts.repository import PostRepository, get_post_repository
from src.domain.models import Post, User
from src.domain.specs import POST_ENTITY
from src.framework import register_entity
from src.framework.dispatch.resource_routes import mount_entity
from src.framework.http.exceptions import ForbiddenError, NotFoundError
from src.framework.http.responses import APIResponse

router = register_entity(POST_ENTITY)


# Whole-supertype face of the polymorphic post entity — one URL family
# (`/posts`) lists every kind. `?kind=<value>` selects the create-form
# template at `GET /posts/form`; the discriminated-union body adapter
# dispatches POST/PATCH bodies by their declared `kind`.
mount_entity(router, POST_ENTITY)


# Maximum body length — chosen to comfortably fit "I have a referral
# that matches; here's a few sentences about availability" without
# becoming an entire email's worth of free text. The cap exists to
# bound the outbound transactional-email size, not to be a UX limit
# the user is meant to feel; bumping it later is cheap.
_MESSAGE_BODY_MAX_LEN = 2000


class _PostMessageBody(BaseModel):
    """Wire shape for `POST /posts/{post_id}/message` — a sender's
    free-text body. The body is rendered as plain text (escaped in
    the HTML part) into the outbound email; there is no DB row.

    Field validators strip surrounding whitespace and reject
    empty-after-strip submissions, matching the implicit contract a
    `<textarea required>` carries on the client side."""

    body: str = Field(..., max_length=_MESSAGE_BODY_MAX_LEN)

    @field_validator("body")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must not be empty")
        return stripped


@router.post("/{post_id}/message", name="post:message_send")
async def send_post_message(
    post_id: UUID,
    body_in: _PostMessageBody,
    request: Request,
    post_repo: PostRepository = Depends(get_post_repository),
    requesting_user: User = Depends(current_active_user),
):
    """In-app "message the poster" event endpoint.

    Event-shaped (RESOURCE_GRAMMAR § "POST /<r>/{id}/<event>") — fires
    an outbound transactional email to the post owner with the
    sender's email on `Reply-To`, persists nothing. The whole point of
    the flow is to let the poster continue the conversation off-platform
    in their own mail client, so any history we'd persist would only
    diverge from what actually happened.

    Authz: the sender must clear `can_access_network` — the same gate
    that controlled visibility of the prior `mailto:` Email button on
    the post detail/list cards. Tightening this to `can_message`
    (clinician-only, per `domain/logic/capabilities.py`) is a separate
    concern; the new endpoint preserves the prior CTA's visibility
    rule so this change is mechanism-only, not also a permission
    change.

    Returns an HTML fragment HTMX swaps over the form in place.
    """
    if not can_access_network(requesting_user):
        raise ForbiddenError(detail="Provider network access required.")
    post = await post_repo.get_by_model_id(Post, post_id)
    if post is None:
        raise NotFoundError(detail="Post not found")
    await send_post_message_email(post=post, sender=requesting_user, body=body_in.body)
    return APIResponse.html_response(
        template_name="posts/_message_sent.html",
        context={"post": post},
        request=request,
        current_user=requesting_user,
    )
