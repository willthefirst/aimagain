from functools import partial

from sqlalchemy import Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import EDUCATION_TYPES, named_check_in

_TABLE = "provider_educations"
_ck = partial(named_check_in, _TABLE)


class ProviderEducation(BaseModel):
    """One row per educational credential held by a clinician. CASCADE
    on the parent FK keeps the credential list in lockstep with the
    `Clinician`. Person-level data — the FK moved from `providers.id`
    to `clinicians.id` in #635 PR A.

    `month_completed` is stored as a "YYYY-MM" string rather than a Date
    because the form captures month-precision only.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("education_type", EDUCATION_TYPES),)

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    education_type = Column(Text, nullable=False)
    institution = Column(Text, nullable=False)
    month_completed = Column(Text, nullable=True)
