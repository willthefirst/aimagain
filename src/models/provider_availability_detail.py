from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Text
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


class ProviderAvailabilityDetail(Base):
    """Per-kind detail row for posts of `kind = 'provider_availability'`.

    `post_id` is both PK and FK to `posts.id`, enforcing 1:1 with the
    parent. CASCADE on the FK keeps the detail row in lockstep with the
    parent's lifecycle.

    Field set follows [`notes/forms_spec.md`](../../notes/forms_spec.md)'s
    Form 2. Enum-typed columns carry CHECK constraints rendered from the
    tuples in `post.py` via `check_in_tuple_sql`. Where a concept appears
    on both forms (`location_state`, `in_person_sessions`/`virtual_sessions`,
    `age_group`, `non_english_services`, `payment_situation`) the column
    types and vocabularies match the corresponding `client_referral_details`
    columns — see the spec's "Field-name overlap" table.

    Multi-select fields from the spec (`desired_times`, `services`,
    `settings`) follow in a separate change once the wire-format extension
    for array-valued checkboxes lands.
    """

    __tablename__ = "provider_availability_details"
    __table_args__ = (
        CheckConstraint(
            check_in_tuple_sql("location_state", US_STATES),
            name="ck_provider_availability_details_location_state",
        ),
        CheckConstraint(
            check_in_tuple_sql("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
            name="ck_provider_availability_details_in_person_sessions",
        ),
        CheckConstraint(
            check_in_tuple_sql("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
            name="ck_provider_availability_details_virtual_sessions",
        ),
        CheckConstraint(
            check_in_tuple_sql("age_group", CLIENT_AGE_GROUPS),
            name="ck_provider_availability_details_age_group",
        ),
        CheckConstraint(
            check_in_tuple_sql("non_english_services", LANGUAGE_PREFERRED_OPTIONS),
            name="ck_provider_availability_details_non_english_services",
        ),
        CheckConstraint(
            check_in_tuple_sql("payment_situation", INSURANCE_OPTIONS),
            name="ck_provider_availability_details_payment_situation",
        ),
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
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)

    # Section 3 — availability
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)

    # Section 4 — featured services
    treatment_modality = Column(Text, nullable=True)
    client_focus = Column(Text, nullable=False)
    age_group = Column(Text, nullable=False)
    non_english_services = Column(Text, nullable=False, server_default="no")

    # Section 5 — insurance
    payment_situation = Column(Text, nullable=False)
    sliding_scale = Column(Boolean, nullable=False)
    cost = Column(Text, nullable=True)
