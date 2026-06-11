"""Wire schemas for the `ClinicianAffiliation` sub-resource of `Clinician`.

A `Clinician` may hold multiple `ClinicianAffiliation` rows after #642 PR 1 (the
UNIQUE on `affiliations.provider_id` was dropped in `7c3c296c9429`).
The clinician edit page surfaces them as an inline list — same UX
pattern as licensures — so each row CRUDs through its own URLs under
``/clinicians/{clinician_id}/clinician_affiliations/{affiliation_id}``.

The fields mirror the per-role attributes on `ClinicianCreate` /
`ClinicianUpdate` (`src/domain/logic/clinicians/schema.py`) — both
schemas land at the same SQLAlchemy table — except that there is no
`(licensures|educations|certifications)` collection here (credentials
are person-level, FK to `clinicians.id` after #635 PR A; they don't
belong to an affiliation row).

Audit snapshots are byte-identical to :class:`ClinicianAffiliationRead`; the
`EntitySpec` defaults `audit_snapshot` to `read_schema` so this module
declares no separate snapshot class.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BeforeValidator

from src.domain.logic.value_objects.location import (
    FlatLocationSchema,
    LocationPartial,
)
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    GENDERS,
    INSURANCE_CARRIERS,
    LOCATION_AVAILABILITY_OPTIONS,
    REFERRAL_SERVICES,
    TREATMENT_MODALITIES,
    TREATMENT_SETTINGS,
)
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

# Steady-state-profile multi-select aliases (#1358 PR-f). Same shape as
# the aliases in `programs/schema.py`: a `Literal[*TUPLE]` layered over
# the shared `scalar_to_list` coercion so a 1-checkbox-checked form post
# still validates. `languages` is deliberately NOT here — it's
# person-level on `Clinician`, not per-affiliation (see the model
# docstring on `ClinicianAffiliation`).
_ServicesField = Annotated[
    list[Literal[*REFERRAL_SERVICES]], BeforeValidator(scalar_to_list)
]
_SettingsField = Annotated[
    list[Literal[*TREATMENT_SETTINGS]], BeforeValidator(scalar_to_list)
]
_ModalitiesField = Annotated[
    list[Literal[*TREATMENT_MODALITIES]], BeforeValidator(scalar_to_list)
]
_AgeGroupsField = Annotated[
    list[Literal[*CLIENT_AGE_GROUPS]], BeforeValidator(scalar_to_list)
]
_GendersField = Annotated[list[Literal[*GENDERS]], BeforeValidator(scalar_to_list)]
# Free-text fields, same idiom as `programs/schema.py`.
_WebsiteField = Annotated[StrippedOptionalText, HtmlUrl()]
_ReferralInstructionsField = Annotated[StrippedOptionalText, HtmlTextarea()]


class ClinicianAffiliationRead(FlatLocationSchema, ReadProjection):
    """Read shape for one ClinicianAffiliation row — what the framework's
    create/update routes return and what the audit snapshot mirrors.

    The `(city, state, zip)` triple arrives flat from ORM attributes
    via `from_attributes` and dumps flat (JSON responses still expose
    `location_city` / `location_state` / `location_zip` at the top
    level). The Location value object owns the cleaning rules.

    `org_id`, `in_person_sessions`, `virtual_sessions`, and `location`
    are nullable here — solo practices (#1311) carry the practice posture
    without an organizational entity, and a freshly-created (stub)
    affiliation has not yet been asked the session-availability or
    location questions. The wire shape mirrors the DB columns, which
    are nullable for the same reason. `LocationPartial` accepts any
    subset of `(city, state, zip)` being set so a partial-location
    affiliation round-trips through `from_attributes` cleanly.
    """

    id: uuid.UUID
    clinician_id: uuid.UUID
    org_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    location: LocationPartial | None = None
    in_person_sessions: str | None = None
    virtual_sessions: str | None = None
    accepts_out_of_network: bool
    in_network_carriers: list[str] = []
    sliding_scale: bool
    cost: str | None = None
    # Steady-state practice profile (#1358 PR-f). Empty list = "no
    # value provided"; mirrors how the program schemas default these.
    services: _ServicesField = []
    settings: _SettingsField = []
    modalities: _ModalitiesField = []
    age_groups: _AgeGroupsField = []
    genders: _GendersField = []
    website: str | None = None
    referral_instructions: str | None = None
    # Denormalized "accepting new patients" cache (#1358 PR-f). The
    # OpeningDetail lifecycle handlers toggle this; the wire surface
    # exposes it as a Read field so directory list/filter UI can show
    # one column without joining.
    currently_accepting_new_patients: bool = False


class ClinicianAffiliationCreate(FlatLocationSchema, WirePayload):
    """Create payload for a new ClinicianAffiliation row.

    `clinician_id` is bound from the URL by the framework's sub-resource
    create handler — not accepted on the wire. Every field is optional
    because a "solo practice" affiliation (#1311) is a valid create
    shape: `org_id` NULL means "no organizational entity"; missing
    location / sessions means "not specified yet, fill in later." A
    completely empty body therefore creates a stub affiliation with
    default values for the NOT NULL columns
    (`accepts_out_of_network=True`, `in_network_carriers=[]`,
    `sliding_scale=False`) and NULLs everywhere else.
    """

    org_id: uuid.UUID | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool = True
    in_network_carriers: InNetworkCarriersField = []
    sliding_scale: bool = False
    cost: StrippedOptionalText = None
    # Steady-state practice profile (#1358 PR-f). Empty list = "no
    # value provided"; mirrors `ProgramCreate`. `currently_accepting_new_patients`
    # is server-managed (toggled by OpeningDetail lifecycle handlers)
    # and intentionally not on Create.
    services: _ServicesField = []
    settings: _SettingsField = []
    modalities: _ModalitiesField = []
    age_groups: _AgeGroupsField = []
    genders: _GendersField = []
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None


class ClinicianAffiliationUpdate(FlatLocationSchema, PartialUpdate):
    """Partial update of an ClinicianAffiliation's per-role fields."""

    org_id: uuid.UUID | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None
    # Steady-state practice profile (#1358 PR-f). List-valued PATCH
    # replaces the whole list; `None` = leave unchanged; `[]` = clear.
    # `currently_accepting_new_patients` is denormalized cache state,
    # mutated server-side by OpeningDetail lifecycle handlers — not on
    # the PATCH surface.
    services: _ServicesField | None = None
    settings: _SettingsField | None = None
    modalities: _ModalitiesField | None = None
    age_groups: _AgeGroupsField | None = None
    genders: _GendersField | None = None
    website: _WebsiteField = None
    referral_instructions: _ReferralInstructionsField = None
