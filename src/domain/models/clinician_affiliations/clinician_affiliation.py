from functools import partial
from typing import ClassVar

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel
from src.framework.persistence.mixins import LocationMixin

from ..enums import LOCATION_AVAILABILITY_OPTIONS, US_STATES, named_check_in

_TABLE = "clinician_affiliations"
_ck = partial(named_check_in, _TABLE)


class ClinicianAffiliation(LocationMixin, BaseModel):
    # Location is deferred during onboarding — users fill it in from the
    # "complete your profile" section after NPI verification.
    _location_nullable: ClassVar[bool] = True
    """The clinician's role at one organization.

    Holds the practice-role attributes that vary per (clinician × org):
    insurance posture, sliding-scale flag, cost, location, modality.
    Person attributes (npi, credentials) live on `Clinician`; org
    metadata lives on `Organization`. A clinician may hold multiple
    affiliations (one per org/role instance).

    Distinct from `OrgRepresentation` (User↔Org authority for Claim B
    of the two-claim verification model). The relationship attribute
    on `Clinician` stays `affiliations` since "the clinician's
    affiliations" reads naturally; only the model class + table got
    the disambiguating `Clinician` prefix.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("location_state", US_STATES),
        _ck("in_person_sessions", LOCATION_AVAILABILITY_OPTIONS),
        _ck("virtual_sessions", LOCATION_AVAILABILITY_OPTIONS),
    )

    clinician_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("clinicians.id", ondelete="RESTRICT"),
        nullable=False,
    )
    clinician = relationship(
        "Clinician", back_populates="clinician_affiliations", lazy="selectin"
    )

    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    org = relationship("Organization", lazy="selectin")

    in_person_sessions = Column(Text, nullable=False)
    virtual_sessions = Column(Text, nullable=False)
    accepts_out_of_network = Column(
        Boolean, nullable=False, server_default=text("1"), default=True
    )
    in_network_carriers = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )
    sliding_scale = Column(
        Boolean, nullable=False, server_default=text("0"), default=False
    )
    cost = Column(Text, nullable=True)
