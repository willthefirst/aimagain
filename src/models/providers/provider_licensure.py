from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Text
from sqlalchemy.types import Uuid

from ..base import BaseModel
from ..enums import LICENSE_TYPES, US_STATES, check_in_tuple_sql

_TABLE = "provider_licensures"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
    )


class ProviderLicensure(BaseModel):
    """One row per professional license held by a provider. CASCADE on the
    parent FK keeps the credential list in lockstep with the `Provider`."""

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("license_type", LICENSE_TYPES),
        _ck("issuing_state", US_STATES),
    )

    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    license_type = Column(Text, nullable=False)
    license_number = Column(Text, nullable=False)
    issuing_state = Column(Text, nullable=False)
    expiration_date = Column(Date, nullable=True)
