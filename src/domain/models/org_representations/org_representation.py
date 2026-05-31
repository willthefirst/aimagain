from functools import partial

from sqlalchemy import (
    TIMESTAMP,
    Column,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from src.framework.persistence.base_model import BaseModel

from ..enums import (
    AUTHORITY_METHODS,
    AUTHORITY_STATUSES,
    ORG_REPRESENTATION_ROLES,
    named_check_in,
)

_TABLE = "org_representations"
_ck = partial(named_check_in, _TABLE)


class OrgRepresentation(BaseModel):
    """The user's authority to act for an organization — carrier of
    Claim B in the two-claim verification model.

    Distinct from `Affiliation`:

    - `Affiliation` links **Clinician ↔ Organization** with practice
      attrs (insurance posture, modality, location). It answers "where
      does this clinician practice?"
    - `OrgRepresentation` links **User ↔ Organization** with authority
      (role + authority_method + authority_status). It answers "who is
      authorized to speak for this org?"

    The two co-exist on the same Org and serve different purposes. A
    clinician can be affiliated with an org without being authorized to
    speak for it, and a user can represent an org without being one of
    its clinicians.

    Authority lifecycle (handoff §6):

    - **First representative** proves authority via one of
      `authorized_official` (NPPES Authorized-Official name-match,
      auto), `domain_email` (verified email at org domain — v1 stub),
      or `admin_review` (fallback).
    - **Subsequent reps** are invited via `rep_approval`: an existing
      verified rep (or admin) sets `approved_by` and flips
      `authority_status` to `verified` via the `authority` state axis.
    - **Revocation** archives the row (`archived_at = NOW()`); does not
      delete. Org-attributed posts authored under the revoked authority
      pause but are preserved per §10.8.

    `UniqueConstraint(user_id, org_id)` keeps a user from holding two
    active representations on the same org simultaneously. Once an
    archived row exists, the constraint blocks a clean reclaim — a
    follow-up may swap this for a partial index on
    `archived_at IS NULL`; until then the application layer should
    refuse to re-create against an archived row and instead un-archive.
    """

    __tablename__ = _TABLE
    __table_args__ = (
        _ck("role", ORG_REPRESENTATION_ROLES),
        _ck("authority_method", AUTHORITY_METHODS),
        _ck("authority_status", AUTHORITY_STATUSES),
        UniqueConstraint(
            "user_id",
            "org_id",
            name="uq_org_representations_user_org",
        ),
    )

    user_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user = relationship("User", foreign_keys=[user_id], lazy="selectin")

    org_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org = relationship("Organization", lazy="selectin")

    role = Column(Text, nullable=False)
    authority_method = Column(Text, nullable=False)
    authority_status = Column(
        Text,
        nullable=False,
        server_default="pending",
        default="pending",
    )
    # `approved_by` points at the verified rep (or admin) who flipped
    # `authority_status` to `verified`. Nullable for first-claimants
    # whose authority was auto-derived (e.g. NPPES AO match) — no human
    # approver in that path.
    approved_by = Column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approver = relationship("User", foreign_keys=[approved_by], lazy="selectin")

    # Revoke-as-archive: set `archived_at` instead of deleting. Org-
    # attributed posts authored under this representation pause but are
    # not destroyed.
    archived_at = Column(TIMESTAMP, nullable=True)
