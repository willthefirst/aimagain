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
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, model_serializer, model_validator

from src.domain.logic.value_objects.location import (
    Location,
    LocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
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
)


def _scalar_to_list(v):
    """Wrap a single string in a one-element list. HTML form posts
    collapse a 1-checkbox-checked group to a scalar (htmx's `json-enc`
    only emits an array when the same name appears 2+ times); this
    normalizes that 1-element case before the `Literal[*TUPLE]` member
    check fires. Mirrors the helper in `providers/schema.py`."""
    if isinstance(v, str):
        return [v]
    return v


InNetworkCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(_scalar_to_list)
]


class AffiliationRead(ReadProjection):
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

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class AffiliationCreate(WirePayload):
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

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class AffiliationUpdate(PartialUpdate):
    """Partial update of an Affiliation's per-role fields."""

    org_id: uuid.UUID | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))
