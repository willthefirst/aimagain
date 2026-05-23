"""Wire schemas for the `Affiliation` sub-resource of `Provider`.

A `Provider` may hold multiple `Affiliation` rows after #642 PR 1 (the
UNIQUE on `affiliations.provider_id` was dropped in `7c3c296c9429`).
The clinician edit page surfaces them as an inline list — same UX
pattern as licensures — so each row CRUDs through its own URLs under
``/clinicians/{clinician_id}/affiliations/{affiliation_id}``.

The fields mirror the per-role attributes on `ProviderCreate` /
`ProviderUpdate` (`src/domain/logic/providers/schema.py`) — both
schemas land at the same SQLAlchemy table — except that there is no
`(licensures|educations|certifications)` collection here (credentials
are person-level, FK to `clinicians.id` after #635 PR A; they don't
belong to an affiliation row).

Audit snapshots are byte-identical to :class:`AffiliationRead`; the
`EntitySpec` defaults `audit_snapshot` to `read_schema` so this module
declares no separate snapshot class.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator

from src.domain.logic.value_objects.location import (
    FlatLocationSchema,
    Location,
    LocationPartial,
)
from src.domain.models.enums import (
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
)
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    WirePayload,
    scalar_to_list,
)

InNetworkCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(scalar_to_list)
]


class AffiliationRead(FlatLocationSchema, ReadProjection):
    """Read shape for one Affiliation row — what the framework's
    create/update routes return and what the audit snapshot mirrors.

    The `(city, state, zip)` triple arrives flat from ORM attributes
    via `from_attributes` and dumps flat (JSON responses still expose
    `location_city` / `location_state` / `location_zip` at the top
    level). The Location value object owns the cleaning rules.
    """

    id: uuid.UUID
    provider_id: uuid.UUID
    clinician_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    location: Location
    in_person_sessions: str
    virtual_sessions: str
    accepts_out_of_network: bool
    in_network_carriers: list[str] = []
    sliding_scale: bool
    cost: str | None = None


class AffiliationCreate(FlatLocationSchema, WirePayload):
    """Create payload for a new Affiliation row.

    `provider_id` is bound from the URL by the framework's sub-resource
    create handler — not accepted on the wire. `clinician_id` is sourced
    from the parent Provider (every affiliation shares its parent's
    clinician); the create handler peels it off the parent row before
    constructing the Affiliation, so this schema doesn't accept it
    either. Only the per-role fields the user actually fills out come
    in here.
    """

    org_id: uuid.UUID
    location: Location
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    accepts_out_of_network: bool = True
    in_network_carriers: InNetworkCarriersField = []
    sliding_scale: bool = False
    cost: StrippedOptionalText = None


class AffiliationUpdate(FlatLocationSchema, PartialUpdate):
    """Partial update of an Affiliation's per-role fields."""

    org_id: uuid.UUID | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None
