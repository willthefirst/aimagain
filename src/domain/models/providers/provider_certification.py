from functools import partial

from sqlalchemy import Column, Date, ForeignKey, Text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import CERTIFICATION_TYPES, named_check_in

_TABLE = "provider_certifications"
_ck = partial(named_check_in, _TABLE)


class ProviderCertification(BaseModel):
    """One row per professional certification held by a clinician.
    CASCADE on the parent FK keeps the credential list in lockstep
    with the `Clinician`. Person-level data — the FK moved from
    `providers.id` to `clinicians.id` in #635 PR A.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("certification_type", CERTIFICATION_TYPES),)

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    certification_type = Column(Text, nullable=False)
    certifying_body = Column(Text, nullable=False)
    expiration_date = Column(Date, nullable=True)
