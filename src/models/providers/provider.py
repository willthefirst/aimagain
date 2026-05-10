from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from ..base import BaseModel
from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, check_in_tuple_sql

_TABLE = "providers"


def _ck(column: str, values: tuple[str, ...]) -> CheckConstraint:
    """`column IN (values)` CHECK named `ck_<table>_<column>`."""
    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{_TABLE}_{column}",
    )


class Provider(BaseModel):
    """Long-lived provider directory entry. Owns the provider's credential
    lists (licensures, educations, certifications) via cascade. A user may
    own multiple `Provider` rows — `uq_provider_profiles_user_id` was
    dropped in `8f20a93effc9` to allow it — so the `user_id` FK is
    intentionally non-unique. Distinct from `ProviderAvailabilityDetail`,
    which is a per-Post detail row tied to one outreach `Post`.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
    )

    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    user = relationship("User")
    practice_name = Column(Text, nullable=False)
    location_city = Column(Text, nullable=False)
    location_state = Column(Text, nullable=False)
    location_zip = Column(Text, nullable=False)
    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)

    licensures = relationship(
        "ProviderLicensure",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    educations = relationship(
        "ProviderEducation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    certifications = relationship(
        "ProviderCertification",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
