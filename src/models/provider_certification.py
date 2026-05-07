from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Text
from sqlalchemy.types import Uuid

from .base import BaseModel
from .post_enums import CERTIFICATION_TYPES, check_in_tuple_sql

_TABLE = "provider_certifications"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
    )


class ProviderCertification(BaseModel):
    """One row per professional certification held by a provider. CASCADE
    on the parent FK keeps the credential list in lockstep with the profile.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("certification_type", CERTIFICATION_TYPES),)

    profile_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("provider_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    certification_type = Column(Text, nullable=False)
    certifying_body = Column(Text, nullable=False)
    expiration_date = Column(Date, nullable=True)
