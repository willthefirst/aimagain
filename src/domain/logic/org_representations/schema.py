"""Wire schemas for `OrgRepresentation` (Claim B carrier — User↔Org).

`Create` is the only path open to non-admins (a user creates their own
representation by claiming an org). `Update` is admin-only (e.g.
changing `role` after an authority promotion). `AuthorityUpdate` is the
state-axis body: admin (or `rep_approval` approver) flipping
`authority_status`.
"""

import uuid
from datetime import datetime
from typing import Literal

from src.domain.models.enums import (
    AUTHORITY_METHODS,
    AUTHORITY_STATUSES,
    ORG_REPRESENTATION_ROLES,
)
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    WirePayload,
)


class OrgRepresentationRead(ReadProjection):
    id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    authority_method: str
    authority_status: str
    approved_by: uuid.UUID | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrgRepresentationCreate(WirePayload):
    """Create a representation for `(user_id, org_id)`.

    `authority_status` defaults to `'pending'` at the DB layer; callers
    don't get to set it on the wire — the `authority` state axis is the
    only path to flip it. `approved_by` is also server-set (the
    requesting user's id, when the authority method is `rep_approval`).
    """

    user_id: uuid.UUID
    org_id: uuid.UUID
    role: Literal[*ORG_REPRESENTATION_ROLES]
    authority_method: Literal[*AUTHORITY_METHODS]


class OrgRepresentationUpdate(PartialUpdate):
    """Admin-only PATCH: change `role` after the row exists. The
    `authority_status` and `archived_at` flows have dedicated state-axis
    handlers; clients don't touch them via PATCH."""

    role: Literal[*ORG_REPRESENTATION_ROLES] | None = None


class OrgRepresentationAuthorityUpdate(WirePayload):
    """Body for `PUT /org_representations/{id}/authority` — admin (or
    `rep_approval` approver) flips the row's `authority_status`."""

    state: Literal[*AUTHORITY_STATUSES]


class OrgRepresentationAuditSnapshot(ReadProjection):
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    authority_method: str
    authority_status: str


class OrgRepresentationAuthorityAuditSnapshot(ReadProjection):
    """Audit `before`/`after` projection for the
    `/org_representations/{id}/authority` state-axis subresource —
    captures only the column this mutation flips."""

    authority_status: str
