from sqlalchemy import CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

_TABLE = "clinicians"

_NPI_FORMAT_CHECK = CheckConstraint(
    "npi IS NULL OR (length(npi) = 10 "
    "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
    name=f"ck_{_TABLE}_npi_format",
)

_PER_ROLE_ATTRS = (
    "org_id",
    "location_city",
    "location_state",
    "location_zip",
    "in_person_sessions",
    "virtual_sessions",
    "accepts_out_of_network",
    "in_network_carriers",
    "sliding_scale",
    "cost",
)


class Clinician(BaseModel):
    """The person behind a directory entry — license-holder, name on
    NPPES, owner of credentials and affiliations.

    A Clinician holds the person-level attributes (NPI, name, credentials)
    that are invariant across affiliations, plus `owner_id` (the user
    account that manages this entry). Practice-role attributes (location,
    insurance, modality) live on `Affiliation` — the (clinician × org)
    join row. A clinician may hold multiple affiliations.
    """

    __tablename__ = _TABLE
    __table_args__ = (_NPI_FORMAT_CHECK,)

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    user = relationship("User", lazy="selectin", foreign_keys=[owner_id])

    npi = Column(Text, nullable=True)
    first_name = Column(Text, nullable=True)
    last_name = Column(Text, nullable=True)

    affiliations = relationship(
        "Affiliation",
        back_populates="clinician",
        order_by="Affiliation.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

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

    def __init__(self, **kwargs):
        from src.domain.models import Affiliation

        per_role = {k: kwargs.pop(k) for k in list(_PER_ROLE_ATTRS) if k in kwargs}
        super().__init__(**kwargs)
        if per_role and not self.affiliations and "affiliations" not in kwargs:
            self.affiliations = [
                Affiliation(
                    clinician=self,
                    org_id=per_role.get("org_id"),
                    location_city=per_role.get("location_city"),
                    location_state=per_role.get("location_state"),
                    location_zip=per_role.get("location_zip"),
                    in_person_sessions=per_role.get("in_person_sessions"),
                    virtual_sessions=per_role.get("virtual_sessions"),
                    accepts_out_of_network=per_role.get("accepts_out_of_network", True),
                    in_network_carriers=per_role.get("in_network_carriers") or [],
                    sliding_scale=per_role.get("sliding_scale", False),
                    cost=per_role.get("cost"),
                )
            ]

    @property
    def primary_affiliation(self):
        return self.affiliations[0] if self.affiliations else None

    @property
    def org_id(self):
        aff = self.primary_affiliation
        return aff.org_id if aff is not None else None

    @org_id.setter
    def org_id(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.org_id = value

    @property
    def org(self):
        aff = self.primary_affiliation
        return aff.org if aff is not None else None

    @org.setter
    def org(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.org = value

    @property
    def org_name(self) -> str | None:
        org = self.org
        return org.name if org is not None else None

    @property
    def location_city(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_city if aff is not None else None

    @location_city.setter
    def location_city(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_city = value

    @property
    def location_state(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_state if aff is not None else None

    @location_state.setter
    def location_state(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_state = value

    @property
    def location_zip(self) -> str | None:
        aff = self.primary_affiliation
        return aff.location_zip if aff is not None else None

    @location_zip.setter
    def location_zip(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.location_zip = value

    @property
    def in_person_sessions(self) -> str | None:
        aff = self.primary_affiliation
        return aff.in_person_sessions if aff is not None else None

    @in_person_sessions.setter
    def in_person_sessions(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.in_person_sessions = value

    @property
    def virtual_sessions(self) -> str | None:
        aff = self.primary_affiliation
        return aff.virtual_sessions if aff is not None else None

    @virtual_sessions.setter
    def virtual_sessions(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.virtual_sessions = value

    @property
    def accepts_out_of_network(self) -> bool | None:
        aff = self.primary_affiliation
        return aff.accepts_out_of_network if aff is not None else None

    @accepts_out_of_network.setter
    def accepts_out_of_network(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.accepts_out_of_network = value

    @property
    def in_network_carriers(self) -> list:
        aff = self.primary_affiliation
        if aff is None or aff.in_network_carriers is None:
            return []
        return aff.in_network_carriers

    @in_network_carriers.setter
    def in_network_carriers(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.in_network_carriers = value

    @property
    def sliding_scale(self) -> bool | None:
        aff = self.primary_affiliation
        return aff.sliding_scale if aff is not None else None

    @sliding_scale.setter
    def sliding_scale(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.sliding_scale = value

    @property
    def cost(self) -> str | None:
        aff = self.primary_affiliation
        return aff.cost if aff is not None else None

    @cost.setter
    def cost(self, value) -> None:
        if self.primary_affiliation is not None:
            self.primary_affiliation.cost = value
