from functools import partial

from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base

from ..enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
    named_check_in,
)

_TABLE = "client_referral_details"
_ck = partial(named_check_in, _TABLE)


class ClientReferralDetail(Base):
    """1:1 detail row for posts of kind = 'client_referral'."""

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        _ck("location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        _ck("client_dem_ages", CLIENT_AGE_GROUPS),
        _ck("insurance", INSURANCE_OPTIONS),
    )

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — client location
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)
    location_in_person = Column(Text, nullable=False)
    location_virtual = Column(Text, nullable=False)
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 2 — demographics
    client_dem_ages = Column(Text, nullable=False)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )

    # Section 3 — description
    description = Column(Text, nullable=False)

    # Section 4 — services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    services_psychotherapy_modality = Column(Text, nullable=True)

    # Section 5 — insurance
    insurance = Column(Text, nullable=False)
