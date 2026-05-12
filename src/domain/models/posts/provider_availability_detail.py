from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

from ..enums import (
    INSURANCE_OPTIONS,
    named_check_in,
)

_TABLE = "provider_availability_details"
_ck = partial(named_check_in, _TABLE)


class ProviderAvailabilityDetail(Base):
    """1:1 detail row for posts of kind = 'provider_availability'.

    Practice + location + delivery-format fields live on the linked
    `Provider` via `provider_id` (#448); this row only carries fields
    that are *per-announcement*, not steady-state practice properties.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("payment_situation", INSURANCE_OPTIONS),)

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # FK to the practice this announcement is for. Practice name, location,
    # and delivery format all live on the linked `Provider` — looked up via
    # `provider.*` in templates and read projections.
    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = relationship("Provider", lazy="selectin")

    # Section 3 — availability
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    # Companion to `desired_times` for cohort dates / fixed program hours
    # (#442). The grid handles "what times of the week am I open"; this
    # captions "May 25 cohort, M-F 9-5". Both can coexist.
    schedule_text = Column(Text, nullable=True)

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )

    # Section 5 — insurance
    payment_situation = Column(Text, nullable=False)
    sliding_scale = Column(Boolean, nullable=False)
    cost = Column(Text, nullable=True)

    # Section 6 — about (free-text core fields)
    description = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
