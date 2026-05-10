from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.types import Uuid

from ..base import BaseModel
from ..enums import EDUCATION_TYPES, check_in_tuple_sql

_TABLE = "provider_educations"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
    )


class ProviderEducation(BaseModel):
    """One row per educational credential held by a provider. CASCADE on
    the parent FK keeps the credential list in lockstep with the `Provider`.

    `month_completed` is stored as a "YYYY-MM" string rather than a Date
    because the form captures month-precision only.
    """

    __tablename__ = _TABLE
    __table_args__ = (_ck("education_type", EDUCATION_TYPES),)

    provider_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
    )
    education_type = Column(Text, nullable=False)
    institution = Column(Text, nullable=False)
    month_completed = Column(Text, nullable=True)
