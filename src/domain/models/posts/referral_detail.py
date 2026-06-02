from functools import partial

from sqlalchemy import JSON, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import Base
from src.framework.persistence.mixins import LocationMixin

from ..enums import (
    GENDERS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    NETWORK_PREFERENCES,
    US_STATES,
    named_check_in,
)

_TABLE = "referral_details"
_ck = partial(named_check_in, _TABLE)


class ReferralDetail(LocationMixin, Base):
    """1:1 detail row for posts of kind = 'referral'.

    Inherits ``(city, state, zip)`` location columns from
    :class:`LocationMixin`; the ``location_state`` CHECK constraint stays
    in ``__table_args__`` because CHECK names are table-prefixed.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        _ck("location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        _ck("insurance_carrier", INSURANCE_CARRIERS),
        _ck("network_preference", NETWORK_PREFERENCES),
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

    # Section 3 — subject / description
    subject = Column(Text, nullable=True)
    description = Column(Text, nullable=False)

    # Section 4 — services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    modalities = Column(JSON, nullable=True, server_default=text("'[]'"), default=list)

    # Section 5 — insurance. Split into two concerns: `network_preference`
    # is the referrer's posture (mandatory / preferred / indifferent) and
    # is always set; `insurance_carrier` is the patient's actual carrier
    # and is nullable (null = self-pay / unknown / no carrier, which is
    # the natural shape when network_preference='no_preference').
    network_preference = Column(
        Text, nullable=False, server_default=text("'no_preference'")
    )
    insurance_carrier = Column(Text, nullable=True)

    # Section 6 — referring clinician. FK to the Clinician row the
    # submitting user designates as the referrer. Nullable so existing
    # rows (created before this field existed) stay valid; the Create
    # schema requires it on new submissions.
    referring_clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="SET NULL"),
        nullable=True,
    )
    referring_clinician = relationship(
        "Clinician",
        foreign_keys=[referring_clinician_id],
        lazy="selectin",
    )

    # Context: the specific `ClinicianAffiliation` the referring clinician
    # is acting under. Mirrors `OpeningDetail.clinician_affiliation_id` —
    # a clinician with several org affiliations refers under one. Nullable
    # (null = no context set), `SET NULL` on affiliation delete.
    clinician_affiliation_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinician_affiliations.id", ondelete="SET NULL"),
        nullable=True,
    )
    clinician_affiliation = relationship("ClinicianAffiliation", lazy="selectin")
