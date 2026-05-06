from sqlalchemy import JSON, Boolean, CheckConstraint, Column, ForeignKey, Text, text
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

_TABLE = "provider_availability_details"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
    )


class ProviderAvailabilityDetail(Base):
    """Per-kind detail row for posts of `kind = 'provider_availability'`.

    `post_id` is both PK and FK to `posts.id`, enforcing 1:1 with the
    parent. CASCADE on the FK keeps the detail row in lockstep with the
    parent's lifecycle.

    Field set follows [`notes/forms_spec.md`](../../notes/forms_spec.md)'s
    Form 2. Enum-typed columns carry CHECK constraints rendered from the
    tuples in `post_enums.py` via `check_in_tuple_sql`. Where a concept
    appears on both forms (`location_state`, `in_person_sessions`/
    `virtual_sessions`, `age_group`, `non_english_services`,
    `payment_situation`) the column types and vocabularies match the
    corresponding `client_referral_details` columns — see the spec's
    "Field-name overlap" table.

    The three JSON multi-select columns (`desired_times`, `services`,
    `settings`) store `list[*]` of controlled-vocabulary tokens. Storing
    as JSON (rather than child join tables) trades SQL set semantics for
    simplicity — all fields are read-once, render-once with no SQL
    queries against their members today. Vocabularies are enforced by
    the Pydantic `Literal[*TUPLE]` on the wire schemas; SQL CHECKs
    against JSON-array members are awkward in SQLite and intentionally
    skipped. `services` and `settings` are required-min-1 on the wire
    (the sibling `client_referral_details` schema allows `services` to
    be empty, and has no `settings` field).
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("age_group", CLIENT_AGE_GROUPS),
        _ck("non_english_services", LANGUAGE_PREFERRED_OPTIONS),
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
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)

    # Section 3 — availability
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)
    desired_times = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Section 4 — featured services
    services = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    settings = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    treatment_modality = Column(Text, nullable=True)
    client_focus = Column(Text, nullable=False)
    age_group = Column(Text, nullable=False)
    non_english_services = Column(Text, nullable=False, server_default="no")

    # Section 5 — insurance
    payment_situation = Column(Text, nullable=False)
    sliding_scale = Column(Boolean, nullable=False)
    cost = Column(Text, nullable=True)
