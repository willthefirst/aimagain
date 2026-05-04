import uuid

from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from .base import BaseModel

POST_KIND_CLIENT_REFERRAL = "client_referral"
POST_KIND_PROVIDER_AVAILABILITY = "provider_availability"
POST_KINDS = (POST_KIND_CLIENT_REFERRAL, POST_KIND_PROVIDER_AVAILABILITY)


class Post(BaseModel):
    """Polymorphic base for all post kinds (joined-table inheritance).

    `posts` holds the shared header (owner, timestamps, kind discriminator);
    each kind has its own child table keyed by `id` FK to `posts.id`. A unified
    timeline (`GET /posts`) reads the parent table; per-kind fields load via
    `with_polymorphic` join or by querying the subclass directly.
    """

    __tablename__ = "posts"
    __mapper_args__ = {
        "polymorphic_identity": "post",
        "polymorphic_on": "kind",
    }

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(Text, nullable=False)

    owner = relationship("User", lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "kind IN ('{}')".format("','".join(POST_KINDS)),
            name="posts_kind_check",
        ),
    )


class ClientReferral(Post):
    """A request from a clinician for client placement / referral support.

    Carries no PII — the form will reflect that constraint to users when fields
    land in a follow-up PR.
    """

    __tablename__ = "client_referrals"
    __mapper_args__ = {"polymorphic_identity": POST_KIND_CLIENT_REFERRAL}

    id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
        default=uuid.uuid4,
    )


class ProviderAvailability(Post):
    """A provider listing their availability / open slots."""

    __tablename__ = "provider_availabilities"
    __mapper_args__ = {"polymorphic_identity": POST_KIND_PROVIDER_AVAILABILITY}

    id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
        default=uuid.uuid4,
    )
