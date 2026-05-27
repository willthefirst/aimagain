from functools import partial

from sqlalchemy import Column, Date, ForeignKey, Text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import LICENSE_TYPES, US_STATES, named_check_in

_TABLE = "provider_licensures"
_ck = partial(named_check_in, _TABLE)


class ClinicianLicensure(BaseModel):
    """One row per professional license held by a clinician. CASCADE on
    the parent FK keeps the credential list in lockstep with the
    `Clinician`. Person-level data — a license follows the person across
    affiliations.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("license_type", LICENSE_TYPES),
        _ck("issuing_state", US_STATES),
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    license_type = Column(Text, nullable=False)
    license_number = Column(Text, nullable=False)
    issuing_state = Column(Text, nullable=False)
    expiration_date = Column(Date, nullable=True)
