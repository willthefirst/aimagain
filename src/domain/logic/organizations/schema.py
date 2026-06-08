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

from src.domain.logic.clinicians.schema import NpiText, RequiredNpiText
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
    npi: str | None = None
    created_at: datetime
    updated_at: datetime


class OrganizationCreate(WirePayload):
    """Create payload. `owner_id` is server-derived from the requesting
    user and not accepted on the wire.

    The create form (``organizations/_form_new_fragment.html``) collects
    just `name` + `npi`. ``is_demo`` stays on the wire schema for
    superuser API consumers; it's surfaced in the edit form for admins.
    """

    name: Annotated[StrippedText, HtmlPattern(maxlength=200)]
    # The org's Type-2 NPI (required). `POST /organizations` runs the
    # Claim-B NPPES verification inline (see
    # `after_create_organization_owner_grant`).
    npi: RequiredNpiText
    # Admin-only: marks this org as a demo environment. See
    # `Organization.is_demo` for the full contract.
    is_demo: bool = False


class OrganizationUpdate(PartialUpdate):
    """Partial update of editable Organization fields."""

    name: StrippedText | None = None
    npi: NpiText = None
    is_demo: bool | None = None


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
