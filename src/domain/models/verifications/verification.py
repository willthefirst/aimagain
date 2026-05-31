from functools import partial

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import (
    VERIFICATION_EVENT_TYPES,
    VERIFICATION_STATUSES,
    VERIFICATION_SUBJECT_TYPES,
    named_check_in,
)

_TABLE = "verifications"
_ck = partial(named_check_in, _TABLE)

# Exactly-one subject: either a clinician (Type-1 NPPES) or an
# organization (Type-2 NPPES + authority transitions). The discriminator
# + the per-side FK presence must agree. Pre-launch refactor — existing
# rows would have been clinician-only, but we don't backfill.
_SUBJECT_SHAPE_CHECK = CheckConstraint(
    "(subject_type = 'clinician' AND clinician_id IS NOT NULL AND org_id IS NULL) "
    "OR (subject_type = 'organization' AND clinician_id IS NULL AND org_id IS NOT NULL)",
    name=f"ck_{_TABLE}_subject_shape",
)


class Verification(BaseModel):
    """One row per verification event against a `Clinician` (Claim A,
    NPPES Type-1) or an `Organization` (Claim B, NPPES Type-2 + authority
    transitions).

    Append-only by convention — no UI exposes update or delete; the
    orchestrator only ever calls `repo.record_for_clinician(...)` /
    `repo.record_for_org(...)`. `created_at` is the effective
    `checked_at`.

    Polymorphic via `subject_type`: a CHECK enforces that exactly one of
    (`clinician_id`, `org_id`) is set, matching the discriminator. Both
    FKs CASCADE on subject delete; the constraint ensures rows never
    orphan-load.

    `evidence` carries the raw NPPES payload + scoring inputs + AO name
    comparison data for `npi_resolved` / `authority_proven` events.
    `event_type` is the §9 closed vocab — every transition that
    recomputes a claim flag appends one event row of the matching type.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("status", VERIFICATION_STATUSES),
        _ck("subject_type", VERIFICATION_SUBJECT_TYPES),
        _ck("event_type", VERIFICATION_EVENT_TYPES),
        _SUBJECT_SHAPE_CHECK,
    )

    subject_type = Column(
        Text,
        nullable=False,
        server_default="clinician",
        default="clinician",
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clinician = relationship("Clinician")

    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    organization = relationship("Organization")

    status = Column(Text, nullable=False)
    event_type = Column(
        Text,
        nullable=False,
        server_default="npi_resolved",
        default="npi_resolved",
    )

    flags = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    nppes_result = Column(JSON, nullable=True)
    # Raw payload — NPPES response, scoring inputs, AO comparison, admin
    # note. The shape varies by `event_type`; readers branch on the
    # discriminator.
    evidence = Column(JSON, nullable=True)
    oig_match = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    name_match_score = Column(Float, nullable=True)
