from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from ..base import BaseModel
from .post_kinds import kind_check_sql


class Post(BaseModel):
    """Parent row for any post-shaped resource.

    Carries identity, ownership, timestamps, and the `kind` discriminator.
    Kind-specific fields live in a per-kind detail table joined on
    `post_id`. The set of allowed kinds — and the per-kind detail
    relationship + field metadata used across the codebase — lives in
    [`post_kinds.py`](post_kinds.py); the CHECK constraint here is
    derived from it via `kind_check_sql()`. Adding a kind means adding
    a registry entry there and a `relationship(...)` line below.

    Per-kind detail tables additionally use the controlled-vocabulary
    tuples in [`../enums.py`](../enums.py) for their enum columns.
    """

    __tablename__ = "posts"
    __table_args__ = (CheckConstraint(kind_check_sql(), name="ck_posts_kind"),)

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
