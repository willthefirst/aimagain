from functools import partial

from sqlalchemy import TIMESTAMP, Boolean, CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import NPI_MATCH_STATUSES, named_check_in

_TABLE = "organizations"
_ck = partial(named_check_in, _TABLE)

# Mirror of `Clinician._NPI_FORMAT_CHECK` — the same NPPES 10-digit shape
# applies to Type-2 (organizational) NPIs.
_NPI_FORMAT_CHECK = CheckConstraint(
    "npi IS NULL OR (length(npi) = 10 "
    "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
    name=f"ck_{_TABLE}_npi_format",
)


class Organization(BaseModel):
    """First-class directory entity for any practice (clinic, group
    practice, health system, solo-practice shell). ``Organization.name``
    is the source of truth for the practice's display name; every
    Clinician is linked to one or more Orgs via ``ClinicianAffiliation``
    and templates read ``clinician.org.name`` directly.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("npi_match_status", NPI_MATCH_STATUSES),
        _NPI_FORMAT_CHECK,
    )

    name = Column(Text, nullable=False)

    # NPPES Type-2 (organizational) NPI. Verified once per Organization;
    # subsequent representatives prove authority against the org through
    # `OrgRepresentation`. See handoff §6 — the org's NPI is verified
    # once, not per rep.
    npi = Column(Text, nullable=True)
    npi_match_status = Column(
        Text, nullable=False, server_default="none", default="none"
    )
    # Denormalized claim-B-prerequisite cache. Set when NPPES confirms
    # the org's Type-2 NPI; `OrgRepresentation.authority_status` carries
    # the per-user authority — both must be true for
    # `capabilities.org_rep_verified(user, org)`.
    org_verified = Column(Boolean, nullable=False, server_default="0", default=False)
    verified_at = Column(TIMESTAMP, nullable=True)
    # Marks this org as a demonstration environment. Clinicians and orgs in
    # demo mode bypass NPPES/OIG and let the user choose a simulated outcome
    # from the profile hub. Admin-set; never writable by regular users.
    is_demo = Column(Boolean, nullable=False, server_default="0", default=False)
    # Cached from NPPES; the AO name-match path
    # (`AuthorityMethod.authorized_official`) compares this against the
    # requesting user's verified `Clinician.first_name`/`last_name` per
    # handoff §6.
    authorized_official_name = Column(Text, nullable=True)

    owner_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    # FK-side ``RESTRICT`` on Programs — deleting an Org with attached
    # Programs fails loudly rather than silently orphaning. The Org →
    # Clinician path is Org → ClinicianAffiliation (#635 PR B);
    # callers that want "clinicians at this org" navigate `org.clinician_affiliations`
    # and read `affiliation.clinician`. ORM relationships are read-only
    # from the Org side.
    programs = relationship("Program", back_populates="organization")
