from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import Base


class ProviderAvailabilityDetail(Base):
    """Per-kind detail row for posts of `kind = 'provider_availability'`.

    Same parent/detail shape as `NoteDetail` and `ClientReferralDetail`:
    `post_id` is both PK and FK to `posts.id`, enforcing 1:1 with the
    parent. CASCADE on the FK keeps the detail row in lockstep with the
    parent's lifecycle.

    MVP: one field (`practice_name`). The full intake form lives in
    `notes/forms_spec.md` and will follow.
    """

    __tablename__ = "provider_availability_details"

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    practice_name = Column(Text, nullable=False)
