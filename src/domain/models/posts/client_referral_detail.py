from functools import partial

from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base
from src.framework.persistence.mixins import LocationMixin

from ..enums import (
    GENDERS,
    INSURANCE_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
    named_check_in,
)

_TABLE = "client_referral_details"
_ck = partial(named_check_in, _TABLE)


class ClientReferralDetail(LocationMixin, Base):
    """1:1 detail row for posts of kind = 'client_referral'.

    Inherits ``(city, state, zip)`` location columns from
    :class:`LocationMixin`; the ``location_state`` CHECK constraint stays
    in ``__table_args__`` because CHECK names are table-prefixed.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        _ck("location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        _ck("insurance", INSURANCE_OPTIONS),
        _ck("gender", GENDERS),
    )

    post_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Section 1 — client location (city/state/zip from LocationMixin)
    location_in_person = Column(Text, nullable=False)
    location_virtual = Column(Text, nullable=False)
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 2 — demographics
    age_groups = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    languages = Column(
        JSON, nullable=False, server_default=text("'[\"en\"]'"), default=lambda: ["en"]
    )
    # Gender identity of the referred client. NOT NULL with a
    # server-side default so the migration backfill picks up existing
    # rows. CHECK constraint above pins the vocabulary to `GENDERS`.
    gender = Column(Text, nullable=False, server_default=text("'prefer_not_to_say'"))

    # Section 3 — description
    description = Column(Text, nullable=False)

    # Section 4 — services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)

    # Section 5 — insurance
    insurance = Column(Text, nullable=False)
