from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import Base


class ClientReferralDetail(Base):
    """Per-kind detail row for posts of `kind = 'client_referral'`.

    Mirrors `NoteDetail`'s shape: `post_id` is both PK and FK to `posts.id`,
    enforcing a 1:1 with the parent. CASCADE on the FK keeps the detail
    row in lockstep with the parent's lifecycle.

    MVP: one field (`description`). The full intake form lives in
    `notes/forms_spec.md` and will follow.
    """

    __tablename__ = "client_referral_details"

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    description = Column(Text, nullable=False)
