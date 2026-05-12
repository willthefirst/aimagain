from functools import partial

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

from ..enums import (
    INSURANCE_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
    named_check_in,
)

_TABLE = "provider_availability_details"
_ck = partial(named_check_in, _TABLE)


class ProviderAvailabilityDetail(Base):
    """1:1 detail row for posts of kind = 'provider_availability'."""

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("payment_situation", INSURANCE_OPTIONS),
    )

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — provider information
    practice_name = Column(Text, nullable=False)
    available_providers = Column(Text, nullable=False)

    # Section 2 — location
    location_city = Column(Text, nullable=True)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=True)

    # Section 3 — availability
    in_person_sessions = Column(Text, nullable=True)
    virtual_sessions = Column(Text, nullable=True)
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    client_focus = Column(Text, nullable=False)
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
