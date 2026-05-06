from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import Base
from .post_enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_OPTIONS,
    LANGUAGE_PREFERRED_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
    check_in_tuple_sql,
)


class ClientReferralDetail(Base):
    """Per-kind detail row for posts of `kind = 'client_referral'`.

    `post_id` is both PK and FK to `posts.id`, enforcing 1:1 with the
    parent. CASCADE on the FK keeps the detail row in lockstep with the
    parent's lifecycle.

    Field set follows [`notes/forms_spec.md`](../../notes/forms_spec.md)'s
    Form 1. Enum-typed columns (`location_state`, `location_in_person`,
    `location_virtual`, `client_dem_ages`, `language_preferred`,
    `insurance`) carry CHECK constraints rendered from the tuples in
    `post.py` via `check_in_tuple_sql`.

    Multi-select fields from the spec (`desired_times`, `services`)
    follow in a separate change once the wire-format extension for
    array-valued checkboxes lands.
    """

    __tablename__ = "client_referral_details"
    __table_args__ = (
        CheckConstraint(
            check_in_tuple_sql("location_state", US_STATES),
            name="ck_client_referral_details_location_state",
        ),
        CheckConstraint(
            check_in_tuple_sql("location_in_person", LOCATION_AVAILABILITY_OPTIONS),
            name="ck_client_referral_details_location_in_person",
        ),
        CheckConstraint(
            check_in_tuple_sql("location_virtual", LOCATION_AVAILABILITY_OPTIONS),
            name="ck_client_referral_details_location_virtual",
        ),
        CheckConstraint(
            check_in_tuple_sql("client_dem_ages", CLIENT_AGE_GROUPS),
            name="ck_client_referral_details_client_dem_ages",
        ),
        CheckConstraint(
            check_in_tuple_sql("language_preferred", LANGUAGE_PREFERRED_OPTIONS),
            name="ck_client_referral_details_language_preferred",
        ),
        CheckConstraint(
            check_in_tuple_sql("insurance", INSURANCE_OPTIONS),
            name="ck_client_referral_details_insurance",
        ),
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

    # Section 2 — demographics
    client_dem_ages = Column(Text, nullable=False)
    language_preferred = Column(Text, nullable=False)

    # Section 3 — description
    description = Column(Text, nullable=False)

    # Section 4 — services
    services_psychotherapy_modality = Column(Text, nullable=True)

    # Section 5 — insurance
    insurance = Column(Text, nullable=False)
