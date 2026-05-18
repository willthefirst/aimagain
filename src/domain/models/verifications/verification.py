from functools import partial

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import VERIFICATION_STATUSES, named_check_in

_TABLE = "verifications"
_ck = partial(named_check_in, _TABLE)


class Verification(BaseModel):
    """One row per nightly verification attempt against a `Provider`.
    Append-only by convention — no UI exposes update or delete, the
    orchestrator only ever calls `repo.record(...)`. `created_at` is
    the effective `checked_at`.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("status", VERIFICATION_STATUSES),)

    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = relationship("Provider")

    status = Column(Text, nullable=False)

    # Free-form bag of string flags surfaced in the audit / UI for the
    # human reviewer, e.g. `nppes_npi_not_found`, `oig_excluded:npi_match`,
    # `nppes_name_mismatch`. The closed vocabulary lives in
    # `src/domain/logic/verifications/scoring.py`; not CHECK'd at the DB
    # layer because the set grows as new flag-emitting checks land.
    flags = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)

    # Raw NPPES API response payload (or `None` if the call failed or
    # was skipped because the provider has no NPI). Stored for the
    # audit trail — what the registry said at the moment of check.
    nppes_result = Column(JSON, nullable=True)

    # OIG/LEIE exclusion-list hit. `True` is a hard disqualifier and
    # forces `status='failed'` (see scoring rules in A3).
    oig_match = Column(Boolean, nullable=False, server_default=text("0"), default=False)

    # NPPES-vs-provider name similarity in `[0.0, 1.0]` via
    # `difflib.SequenceMatcher`, or `None` if NPPES wasn't queried.
    name_match_score = Column(Float, nullable=True)
