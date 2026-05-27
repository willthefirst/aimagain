from functools import partial

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import VERIFICATION_STATUSES, named_check_in

_TABLE = "verifications"
_ck = partial(named_check_in, _TABLE)


class Verification(BaseModel):
    """One row per nightly verification attempt against a `Clinician`.
    Append-only by convention — no UI exposes update or delete, the
    orchestrator only ever calls `repo.record(...)`. `created_at` is
    the effective `checked_at`.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("status", VERIFICATION_STATUSES),)

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clinician = relationship("Clinician")

    status = Column(Text, nullable=False)

    flags = Column(JSON, nullable=False, server_default=text("'[]'"), default=list)
    nppes_result = Column(JSON, nullable=True)
    oig_match = Column(Boolean, nullable=False, server_default=text("0"), default=False)
    name_match_score = Column(Float, nullable=True)
