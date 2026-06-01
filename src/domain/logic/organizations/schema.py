"""Wire schemas for the `Organization` directory entity.

`Read` exposes every persisted column, including the denormalized
`root_org_id` (callers can filter subtrees client-side without a
separate fetch). `Create` accepts only fields the client controls:
`owner_id` and `root_org_id` are server-derived (owner from the
requesting user; root from the parent chain per the repository
invariant — see ``src/domain/models/organizations/README.md``).

`Update` is a partial patch of the same client-controlled fields.
Moving a node in the tree (`parent_org_id` change) is allowed via
update, but the same root-recomputation invariant the repository
enforces on create applies — handled in the repository when the
attribute is touched.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel

from src.domain.models.enums import ORGANIZATION_TYPES
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedText,
    WirePayload,
)


class OrganizationRead(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    type: str
    parent_org_id: uuid.UUID | None = None
    root_org_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(WirePayload):
    """Create payload. `owner_id` and `root_org_id` are server-derived
    and not accepted on the wire."""

    name: Annotated[StrippedText, HtmlPattern(maxlength=200)]
    type: Literal[*ORGANIZATION_TYPES]
    # Blank HTML form input (`""`) is coerced to `None` at the
    # `WirePayload` layer — see `_coerce_blank_strings_on_nullable_scalars`.
    parent_org_id: uuid.UUID | None = None


class OrganizationUpdate(PartialUpdate):
    """Partial update. Touching `parent_org_id` triggers
    `root_org_id` recomputation in the repository — clients don't
    set the root directly."""

    name: StrippedText | None = None
    type: Literal[*ORGANIZATION_TYPES] | None = None
    parent_org_id: uuid.UUID | None = None


# --- Admin verification-state axis ---------------------------------------


class OrganizationVerificationStateUpdate(BaseModel):
    """Body for `PUT /organizations/{id}/verification` — admin override
    of `npi_match_status`. Same vocab + semantics as the Clinician-side
    axis (see `ClinicianVerificationStateUpdate`)."""

    state: Literal["matched", "mismatch", "pending"]


class OrganizationVerificationAuditSnapshot(ReadProjection):
    """Audit `before`/`after` for the `/organizations/{id}/verification`
    axis. Captures only the column the axis mutates."""

    npi_match_status: str
