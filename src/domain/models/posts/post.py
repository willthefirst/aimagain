from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from .post_kinds import POST_KINDS


class Post(BaseModel):
    """Parent row for any post-shaped resource.

    Carries identity, ownership, timestamps, and the `kind` discriminator.
    Kind-specific fields live in a per-kind detail table joined on
    `post_id`. The set of allowed kinds — and the per-kind detail
    relationship + field metadata used across the codebase — lives in
    [`post_kinds.py`](post_kinds.py); the CHECK constraint here is
    derived from it via `POST_KINDS.check_sql()`. Adding a kind means
    adding a registry entry there and a `relationship(...)` line below.

    Per-kind detail tables additionally use the controlled-vocabulary
    tuples in [`../enums.py`](../enums.py) for their enum columns.
    """

    __tablename__ = "posts"
    __table_args__ = (CheckConstraint(POST_KINDS.check_sql(), name="ck_posts_kind"),)

    kind = Column(Text, nullable=False)
    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    owner = relationship("User", lazy="joined")
    referral_detail = relationship(
        "ReferralDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    opening_detail = relationship(
        "OpeningDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    intake_detail = relationship(
        "IntakeDetail",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
