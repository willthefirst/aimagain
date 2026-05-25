from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.domain.models.enums import (
    AVAILABILITY_STATES,
    OPENING_TYPES,
    named_check_in,
)
from src.framework.persistence.base_model import Base

_TABLE = "opening_details"


class OpeningDetail(Base):
    """1:1 detail row for posts of kind = 'clinician_opening'.

    Practice + location + delivery-format fields live on the linked
    `Provider` via `provider_id`; insurance posture + sliding-scale +
    cost also live on `Provider`. This row only carries fields that are
    *per-announcement*, not steady-state practice properties.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        named_check_in(_TABLE, "opening_type", OPENING_TYPES),
        named_check_in(_TABLE, "availability_state", AVAILABILITY_STATES),
    )

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
    # Companion to `desired_times` for cohort dates / fixed program hours.
    # The grid handles "what times of the week am I open"; this captions
    # "May 25 cohort, M-F 9-5". Both can coexist.
    schedule_text = Column(Text, nullable=True)

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Genders this practice serves. JSON-array of `GENDERS` tokens
    # (vocabulary enforced on the wire by Pydantic, not via SQL CHECK —
    # same shape as `services` / `settings` / `age_groups`). Empty list
    # is allowed both at rest and on the wire — "no restriction stated."
    genders = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Section 5 — slot shape (T3 fields)
    opening_type = Column(Text, nullable=True)
    specialties = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    population_tags = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    fee_low = Column(Integer, nullable=True)
    fee_high = Column(Integer, nullable=True)
    payment_types = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    availability_state = Column(Text, nullable=True)
    # Peer-facing note (≤280 chars enforced in Pydantic, not at DB level).
    colleague_note = Column(Text, nullable=True)
    note_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_confirmed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("(CURRENT_TIMESTAMP)"),
        default=lambda: datetime.now(timezone.utc),
    )

    # Section 6 — about (free-text core fields)
    description = Column(Text, nullable=True)
    referral_instructions = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
