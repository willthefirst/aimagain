from functools import partial

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import NPI_MATCH_STATUSES, named_check_in

_TABLE = "clinicians"
_ck = partial(named_check_in, _TABLE)

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
    insurance, modality) live on `ClinicianAffiliation` — the (clinician × org)
    join row. A clinician may hold multiple affiliations.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _NPI_FORMAT_CHECK,
        _ck("npi_match_status", NPI_MATCH_STATUSES),
    )

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    user = relationship("User", lazy="selectin", foreign_keys=[owner_id])

    npi = Column(Text, nullable=True)
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)

    # Affirming-identity claims (who the clinician *is* — invariant across
    # affiliations, like credentials). JSON list of `AffirmingIdentity`
    # tokens; empty array means "none stated". Vocabulary check happens on
    # the wire (Pydantic `Literal[*AFFIRMING_IDENTITIES]`); no SQL CHECK
    # against JSON array members, same pattern as `in_network_carriers` on
    # `ClinicianAffiliation`.
    affirming_identities = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # Clinical-niche tags — free-form vocabulary (#1358 PR-c). Examples
    # from the referral corpus: "DGBI", "catatonia", "ADHD in women",
    # "psychedelic-knowledgeable", "minor consent", "complex trauma".
    # Person-level (the niche moves with the clinician across affiliations),
    # symmetric to `ReferralDetail.clinical_niches` on the request side.
    # Deliberately NOT an enum — the vocabulary is too open-ended on day
    # one; we plan to promote heavily-used tags to `Literal[*ENUM]` once
    # usage patterns stabilize. Each tag is a stripped non-empty string;
    # no SQL CHECK against array members (vocabulary is open).
    clinical_niches = Column(
        JSON, nullable=False, server_default=text("'[]'"), default=list
    )

    # NPPES Type-1 match state. Source-of-truth field for Claim A: the
    # `verifications` table is the event log; this column is the cache
    # `capabilities.clinician_verified(user)` reads. `none` = no NPI
    # submitted, `pending` = worker hasn't resolved yet, `matched` =
    # NPPES legal-name match cleared the threshold, `mismatch` = admin
    # closed a soft mismatch (per handoff §10.1, the worker never
    # auto-transitions to `mismatch`).
    npi_match_status = Column(
        Text, nullable=False, server_default="none", default="none"
    )
    npi_verified_at = Column(TIMESTAMP, nullable=True)

    # Denormalized cache of Claim A. Recomputed by
    # `recompute_clinician_claim(...)` on every transition that changes
    # `npi_match_status`. Lets the capabilities predicate run without
    # re-reading the column on every check.
    clinician_verified = Column(
        Boolean, nullable=False, server_default="0", default=False
    )
    verified_at = Column(TIMESTAMP, nullable=True)
    # First-ever verification timestamp; preserved across regressions.
    # Drives `capabilities.can_act_as_provider(...)` retention rule per
    # handoff §7.1: once verified, the user keeps full feed access even
    # if a license later lapses.
    ever_verified_at = Column(TIMESTAMP, nullable=True)

    clinician_affiliations = relationship(
        "ClinicianAffiliation",
        back_populates="clinician",
        order_by="ClinicianAffiliation.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    licensures = relationship(
        "ClinicianLicensure",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    educations = relationship(
        "ClinicianEducation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    certifications = relationship(
        "ClinicianCertification",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        from src.domain.models import ClinicianAffiliation

        per_role = {k: kwargs.pop(k) for k in list(_PER_ROLE_ATTRS) if k in kwargs}
        super().__init__(**kwargs)
        if (
            per_role
            and not self.clinician_affiliations
            and "clinician_affiliations" not in kwargs
        ):
            self.clinician_affiliations = [
                ClinicianAffiliation(
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
    def primary_clinician_affiliation(self):
        return self.clinician_affiliations[0] if self.clinician_affiliations else None

    def _require_primary_affiliation(self, attr_name: str):
        """Setter guard for every per-affiliation proxy below.

        Per-affiliation fields (location, availability, insurance posture,
        cost, org_id) live on :class:`ClinicianAffiliation`, not on this
        row. Writing through the proxy when no affiliation exists used to
        silently no-op — :class:`Clinician` accepted the write and dropped
        it, which surfaced in production as "the edit form returned 200
        but nothing saved" once create-time affiliation became optional.
        The cure is to refuse the write loudly: callers must give the
        clinician an affiliation first (PR-2 auto-creates a stub for solo
        clinicians) or write directly to the target affiliation.
        """
        aff = self.primary_clinician_affiliation
        if aff is None:
            raise ValueError(
                f"cannot set {attr_name!r} on a Clinician with no "
                "ClinicianAffiliation; per-affiliation fields require a "
                "primary affiliation"
            )
        return aff

    @property
    def org_id(self):
        aff = self.primary_clinician_affiliation
        return aff.org_id if aff is not None else None

    @org_id.setter
    def org_id(self, value) -> None:
        self._require_primary_affiliation("org_id").org_id = value

    @property
    def org(self):
        aff = self.primary_clinician_affiliation
        return aff.org if aff is not None else None

    @org.setter
    def org(self, value) -> None:
        self._require_primary_affiliation("org").org = value

    @property
    def org_name(self) -> str | None:
        org = self.org
        return org.name if org is not None else None

    @property
    def location_city(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.location_city if aff is not None else None

    @location_city.setter
    def location_city(self, value) -> None:
        self._require_primary_affiliation("location_city").location_city = value

    @property
    def location_state(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.location_state if aff is not None else None

    @location_state.setter
    def location_state(self, value) -> None:
        self._require_primary_affiliation("location_state").location_state = value

    @property
    def location_zip(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.location_zip if aff is not None else None

    @location_zip.setter
    def location_zip(self, value) -> None:
        self._require_primary_affiliation("location_zip").location_zip = value

    @property
    def in_person_sessions(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.in_person_sessions if aff is not None else None

    @in_person_sessions.setter
    def in_person_sessions(self, value) -> None:
        self._require_primary_affiliation("in_person_sessions").in_person_sessions = (
            value
        )

    @property
    def virtual_sessions(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.virtual_sessions if aff is not None else None

    @virtual_sessions.setter
    def virtual_sessions(self, value) -> None:
        self._require_primary_affiliation("virtual_sessions").virtual_sessions = value

    @property
    def accepts_out_of_network(self) -> bool | None:
        aff = self.primary_clinician_affiliation
        return aff.accepts_out_of_network if aff is not None else None

    @accepts_out_of_network.setter
    def accepts_out_of_network(self, value) -> None:
        self._require_primary_affiliation(
            "accepts_out_of_network"
        ).accepts_out_of_network = value

    @property
    def in_network_carriers(self) -> list:
        aff = self.primary_clinician_affiliation
        if aff is None or aff.in_network_carriers is None:
            return []
        return aff.in_network_carriers

    @in_network_carriers.setter
    def in_network_carriers(self, value) -> None:
        self._require_primary_affiliation("in_network_carriers").in_network_carriers = (
            value
        )

    @property
    def sliding_scale(self) -> bool | None:
        aff = self.primary_clinician_affiliation
        return aff.sliding_scale if aff is not None else None

    @sliding_scale.setter
    def sliding_scale(self, value) -> None:
        self._require_primary_affiliation("sliding_scale").sliding_scale = value

    @property
    def cost(self) -> str | None:
        aff = self.primary_clinician_affiliation
        return aff.cost if aff is not None else None

    @cost.setter
    def cost(self, value) -> None:
        self._require_primary_affiliation("cost").cost = value
