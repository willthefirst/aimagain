from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel


class Post(BaseModel):
    """Parent row for any post-shaped resource.

    Carries identity, ownership, timestamps, and the `kind` discriminator.
    Kind-specific fields live in a per-kind detail table joined on
    `post_id`. Kinds today: `'client_referral'` (→ `ClientReferralDetail`),
    `'provider_availability'` (→ `ProviderAvailabilityDetail`). Adding a
    kind means widening the CHECK here, adding a detail table, and adding
    a `relationship(...)` below.
    """

    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('client_referral', 'provider_availability')",
            name="ck_posts_kind",
        ),
    )

    kind = Column(Text, nullable=False)
    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner = relationship("User", lazy="joined")
    client_referral_detail = relationship(
        "ClientReferralDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    provider_availability_detail = relationship(
        "ProviderAvailabilityDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
