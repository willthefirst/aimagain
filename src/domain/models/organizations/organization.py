from functools import partial

from sqlalchemy import TIMESTAMP, Boolean, CheckConstraint, Column, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import NPI_MATCH_STATUSES, ORGANIZATION_TYPES, named_check_in

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
    """First-class directory entity for clinics, group practices, health
    systems, and solo-practice shells. ``Organization.name`` is the
    source of truth for the practice's display name; every Clinician
    is linked to one or more Orgs via Affiliation and templates
    read ``clinician.org.name`` directly.

    Hierarchy is modeled as a self-referential tree via ``parent_org_id``
    (nullable; a root org has ``parent_org_id IS NULL``). ``root_org_id``
    is denormalized so subtree lookups stay one indexed read instead of
    a recursive CTE. See ``README.md`` in this directory for the
    insert-time invariant tying the two columns together.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("type", ORGANIZATION_TYPES),
        _ck("npi_match_status", NPI_MATCH_STATUSES),
        _NPI_FORMAT_CHECK,
    )

    name = Column(Text, nullable=False)
    type = Column(Text, nullable=False)

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
    parent_org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    root_org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User")
    # ``lazy="selectin"`` so the detail template can resolve the parent's
    # *name* without re-issuing IO inside Jinja (async sessions disallow
    # implicit lazy-loads). Same pattern as ``Clinician.org`` — any
    # relationship a template dereferences must be eagerly loaded at the
    # session boundary.
    parent = relationship(
        "Organization",
        remote_side="Organization.id",
        foreign_keys=[parent_org_id],
        lazy="selectin",
        join_depth=1,
    )
    # FK-side ``RESTRICT`` on Programs — deleting an Org with attached
    # Programs fails loudly rather than silently orphaning. The Org →
    # Clinician path is Org → Affiliation (#635 PR B);
    # callers that want "clinicians at this org" navigate `org.affiliations`
    # and read `affiliation.clinician`. ORM relationships are read-only
    # from the Org side.
    programs = relationship("Program", back_populates="organization")
