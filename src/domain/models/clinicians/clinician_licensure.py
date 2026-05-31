from functools import partial

from sqlalchemy import TIMESTAMP, Boolean, Column, Date, ForeignKey, Text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import LICENSE_STATUSES, LICENSE_TYPES, US_STATES, named_check_in

_TABLE = "clinician_licensures"
_ck = partial(named_check_in, _TABLE)


class ClinicianLicensure(BaseModel):
    """One row per professional license held by a clinician. CASCADE on
    the parent FK keeps the credential list in lockstep with the
    `Clinician`. Person-level data — a license follows the person across
    affiliations.

    `status` is derived from `expiration_date` + `attested_active` by the
    nightly worker but stored for query speed — Claim A capability checks
    and the directory-listing filter both restrict on "has an active
    license" without recomputing per row.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("license_type", LICENSE_TYPES),
        _ck("issuing_state", US_STATES),
        _ck("status", LICENSE_STATUSES),
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    license_type = Column(Text, nullable=False)
    license_number = Column(Text, nullable=False)
    issuing_state = Column(Text, nullable=False)
    # `expiration_date` is the handoff's `expires_on`; keeping the
    # existing column name avoids form/schema/audit churn.
    expiration_date = Column(Date, nullable=True)

    # Computed cache derived from `expiration_date` and `attested_active`
    # by the nightly worker; persisted so `clinician_verified` recompute
    # and the directory filter don't re-derive per row.
    status = Column(Text, nullable=False, server_default="pending", default="pending")
    # Clinician-asserted "this license is currently in good standing."
    # Combined with `expiration_date` to set `status`. Re-attestation is
    # the Claim-A re-verify path per handoff §10 (Phase 5's `_reverify.html`).
    attested_active = Column(Boolean, nullable=False, server_default="0", default=False)
    attested_at = Column(TIMESTAMP, nullable=True)
