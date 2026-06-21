"""Wire schemas for the `ClinicianAffiliation` sub-resource of `Clinician`.

A `Clinician` may hold multiple `ClinicianAffiliation` rows after #642 PR 1 (the
UNIQUE on `affiliations.provider_id` was dropped in `7c3c296c9429`).
The clinician edit page surfaces them as an inline list — same UX
pattern as licensures — so each row CRUDs through its own URLs under
``/clinicians/{clinician_id}/clinician_affiliations/{affiliation_id}``.

The affiliation is **steady-state context** only: location (city/area +
state, no ZIP), insurance posture, and how-to-refer fields. The
per-announcement profile (service lines, delivery format, cohort served,
cost) lives on ``OpeningDetail`` (the opening post), not here.

Audit snapshots are byte-identical to :class:`ClinicianAffiliationRead`; the
`EntitySpec` defaults `audit_snapshot` to `read_schema` so this module
declares no separate snapshot class.
"""

import uuid
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BeforeValidator

from src.domain.logic.value_objects.location import (
    FlatLocationSchema,
    ReferralLocationPartial,
)
from src.domain.models.enums import INSURANCE_CARRIERS
from src.framework.rendering.form_fields import HtmlTextarea, HtmlUrl
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
# Free-text fields, same idiom as `programs/schema.py`.
_WebsiteField = Annotated[StrippedOptionalText, HtmlUrl()]
_ReferralInstructionsField = Annotated[StrippedOptionalText, HtmlTextarea()]


class ClinicianAffiliationRead(FlatLocationSchema, ReadProjection):
    """Read shape for one ClinicianAffiliation row — what the framework's
    create/update routes return and what the audit snapshot mirrors.

    The `(city, state)` pair arrives flat from ORM attributes via
    `from_attributes` and dumps flat (JSON responses still expose
    `location_city` / `location_state` at the top level). No ZIP — the
    affiliation models a practice region like a referral does.

    `org_id` and `location` are nullable here — solo practices (#1311)
    carry the practice posture without an organizational entity, and a
    freshly-created (stub) affiliation has not yet been asked the location
    question. `ReferralLocationPartial` accepts city and/or state being
    set so a partial-location affiliation round-trips cleanly.
    """

    _location_subfields: ClassVar[tuple[str, ...]] = ("city", "state")

    id: uuid.UUID
    clinician_id: uuid.UUID
    org_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    location: ReferralLocationPartial | None = None
    accepts_out_of_network: bool
    in_network_carriers: list[str] = []
    sliding_scale: bool
    website: str | None = None
    referral_instructions: str | None = None
    # Denormalized "accepting new patients" cache. The OpeningDetail
    # lifecycle handlers toggle this; the wire surface exposes it as a
    # Read field so directory list/filter UI can show one column without
    # joining.
    currently_accepting_new_patients: bool = False


class ClinicianAffiliationCreate(FlatLocationSchema, WirePayload):
    """Create payload for a new ClinicianAffiliation row.

    `clinician_id` is bound from the URL by the framework's sub-resource
    create handler — not accepted on the wire. Every field is optional
    because a "solo practice" affiliation (#1311) is a valid create
    shape: `org_id` NULL means "no organizational entity"; missing
    location means "not specified yet, fill in later." A completely empty
    body therefore creates a stub affiliation with default values for the
    NOT NULL columns (`accepts_out_of_network=True`, `in_network_carriers=[]`,
    `sliding_scale=False`) and NULLs everywhere else.
    """

    _location_subfields: ClassVar[tuple[str, ...]] = ("city", "state")

    org_id: uuid.UUID | None = None
    location: ReferralLocationPartial | None = None
    accepts_out_of_network: bool = True
    in_network_carriers: InNetworkCarriersField = []
    sliding_scale: bool = False
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None


class ClinicianAffiliationUpdate(FlatLocationSchema, PartialUpdate):
    """Partial update of an ClinicianAffiliation's per-role fields."""

    _location_subfields: ClassVar[tuple[str, ...]] = ("city", "state")

    org_id: uuid.UUID | None = None
    location: ReferralLocationPartial | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None
