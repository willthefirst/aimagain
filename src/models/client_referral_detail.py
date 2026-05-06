from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Text, text
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

_TABLE = "client_referral_details"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
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
    `post_enums.py` via `check_in_tuple_sql`.

    `desired_times` is a JSON column of `list[DESIRED_TIME_SLOTS]`.
    Storing as JSON (rather than a child join table) trades SQL set
    semantics for simplicity — the field is read-once, render-once with
    no SQL queries against its members today. Vocabulary is enforced by
    the Pydantic `Literal[*DESIRED_TIME_SLOTS]` on the wire schemas;
    a SQL CHECK against JSON-array members is awkward in SQLite and
    intentionally skipped.

    The remaining multi-select fields from the spec (`services`) follow
    in a separate change.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("location_in_person", LOCATION_AVAILABILITY_OPTIONS),
        _ck("location_virtual", LOCATION_AVAILABILITY_OPTIONS),
        _ck("client_dem_ages", CLIENT_AGE_GROUPS),
        _ck("language_preferred", LANGUAGE_PREFERRED_OPTIONS),
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
    language_preferred = Column(Text, nullable=False)

    # Section 3 — description
    description = Column(Text, nullable=False)

    # Section 4 — services
    services_psychotherapy_modality = Column(Text, nullable=True)

    # Section 5 — insurance
    insurance = Column(Text, nullable=False)
