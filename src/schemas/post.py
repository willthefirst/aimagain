"""Wire schemas for posts.

`Post` is a parent row with a `kind` discriminator and a per-kind detail
table. The wire surface mirrors that shape: `PostCreate` / `PostUpdate`
/ `PostRead` / `PostAuditSnapshot` are kind-discriminated unions on the
(required) `kind` field.

`post_audit_snapshot(post)` validates a SQLAlchemy `Post` against the
union and returns a JSON-mode dump for the audit row.

The per-kind detail relationship + fields live in
[`src/models/post_kinds.py`](../models/post_kinds.py) — this module's
`_flatten_post_to_dict` reads from that registry. Adding a kind here
means the four Pydantic variant classes (Read/Create/Update/
AuditSnapshot) plus their entry in the discriminated unions; everything
else flows from the registry.

Controlled-vocabulary fields (state, age group, etc.) are typed as
`Literal[*TUPLE]` against tuples in `src/models/post.py` so the
schema's accepted values stay in lockstep with the DB CHECK
constraints. The guardrail test
`test_schema_literals_match_model_tuples` (in `test_post.py`) asserts
this; if you add or rename a vocabulary, update both sides and the
test will keep them honest.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from src.models import REGISTERED_KINDS
from src.models.post_enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_OPTIONS,
    LANGUAGE_PREFERRED_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)

# --- Shared validators --------------------------------------------------

_ZIP_RE = re.compile(r"^\d{5}$")


def _strip_required(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


def _strip_required_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    return _strip_required(v)


def _strip_optional(v: str | None) -> str | None:
    """Strip whitespace; collapse empty/whitespace-only to `None`. Used for
    optional free-text fields where '' from a blank input means absent."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def _validate_zip(v: str) -> str:
    v = v.strip()
    if not _ZIP_RE.match(v):
        raise ValueError("must be a 5-digit ZIP code")
    return v


def _validate_zip_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    return _validate_zip(v)


# --- Shared flatten helper ----------------------------------------------


def _flatten_post_to_dict(post) -> dict | None:
    """Flatten a SQLAlchemy `Post` (parent + per-kind detail) to a flat
    dict keyed on the parent + detail field names.

    Returns `None` when the input doesn't look like a `Post` (e.g. it's
    already a flat dict from a direct constructor call) so callers can
    fall back to passing the input through unchanged. Read variants and
    audit-snapshot variants share this helper; Pydantic silently drops
    fields that aren't declared on a given variant (neither Read nor
    AuditSnapshot uses `extra="forbid"`), so the same flat dict feeds
    both shapes. Per-kind metadata comes from `REGISTERED_KINDS`.
    """
    kind = getattr(post, "kind", None)
    spec = REGISTERED_KINDS.get(kind)
    if spec is None:
        return None
    detail = getattr(post, spec.detail_relationship, None)
    if detail is None:
        return None
    return {
        "id": getattr(post, "id", None),
        "kind": kind,
        "owner_id": getattr(post, "owner_id", None),
        "created_at": getattr(post, "created_at", None),
        "updated_at": getattr(post, "updated_at", None),
        **{f: getattr(detail, f) for f in spec.detail_fields},
    }


# --- Read projections ---------------------------------------------------


class _PostReadBase(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        return _flatten_post_to_dict(data) or data


class ClientReferralRead(_PostReadBase):
    kind: Literal["client_referral"]
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: str
    services_psychotherapy_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS]


class ProviderAvailabilityRead(_PostReadBase):
    kind: Literal["provider_availability"]
    practice_name: str
    available_providers: str
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    treatment_modality: str | None = None
    client_focus: str
    age_group: Literal[*CLIENT_AGE_GROUPS]
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    payment_situation: Literal[*INSURANCE_OPTIONS]
    sliding_scale: bool
    cost: str | None = None


PostRead = Annotated[
    Union[ClientReferralRead, ProviderAvailabilityRead],
    Field(discriminator="kind"),
]
post_read_adapter: TypeAdapter = TypeAdapter(PostRead)


# --- Create payloads ----------------------------------------------------


class ClientReferralCreate(BaseModel):
    """Create payload for `kind='client_referral'`. Field set follows
    [`notes/forms_spec.md`](../../notes/forms_spec.md) Form 1; multi-select
    fields (`desired_times`, `services`) follow in a separate change."""

    kind: Literal["client_referral"]
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: str
    services_psychotherapy_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS]

    model_config = ConfigDict(extra="forbid")

    @field_validator("location_city", "description")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _validate_zip(cls, v: str) -> str:
        return _validate_zip(v)

    @field_validator("services_psychotherapy_modality")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return _strip_optional(v)


class ProviderAvailabilityCreate(BaseModel):
    """Create payload for `kind='provider_availability'`. Field set follows
    [`notes/forms_spec.md`](../../notes/forms_spec.md) Form 2; multi-select
    fields (`desired_times`, `services`, `settings`) follow in a separate
    change."""

    kind: Literal["provider_availability"]
    practice_name: str
    available_providers: str
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    treatment_modality: str | None = None
    client_focus: str
    age_group: Literal[*CLIENT_AGE_GROUPS]
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS] = "no"
    payment_situation: Literal[*INSURANCE_OPTIONS]
    sliding_scale: bool
    cost: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "practice_name",
        "available_providers",
        "location_city",
        "client_focus",
    )
    @classmethod
    def _strip_required(cls, v: str) -> str:
        return _strip_required(v)

    @field_validator("location_zip")
    @classmethod
    def _validate_zip(cls, v: str) -> str:
        return _validate_zip(v)

    @field_validator("treatment_modality", "cost")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return _strip_optional(v)


PostCreate = Annotated[
    Union[ClientReferralCreate, ProviderAvailabilityCreate],
    Field(discriminator="kind"),
]
post_create_adapter: TypeAdapter = TypeAdapter(PostCreate)


# --- Update payloads (partial) ------------------------------------------
#
# Every per-kind editable field is made `T | None = None` and the
# at-least-one-field rule is enforced in a model validator. Fields whose
# value is `None` are interpreted as "leave unchanged" by
# `PostRepository.update_post`. Optional free-text fields can therefore
# only be *set* via PATCH today, not cleared back to `None`; that's a
# pre-existing repository semantic and intentionally out of scope here.


def _at_least_one_editable_field(self) -> None:
    fields = type(self).model_fields
    if all(getattr(self, name) is None for name in fields if name != "kind"):
        raise ValueError("at least one editable field must be provided")


class ClientReferralUpdate(BaseModel):
    kind: Literal["client_referral"]
    location_city: str | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: str | None = None
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS] | None = None
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS] | None = None
    description: str | None = None
    services_psychotherapy_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("location_city", "description")
    @classmethod
    def _strip_required(cls, v: str | None) -> str | None:
        return _strip_required_or_none(v)

    @field_validator("location_zip")
    @classmethod
    def _validate_zip(cls, v: str | None) -> str | None:
        return _validate_zip_or_none(v)

    @field_validator("services_psychotherapy_modality")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ClientReferralUpdate":
        _at_least_one_editable_field(self)
        return self


class ProviderAvailabilityUpdate(BaseModel):
    kind: Literal["provider_availability"]
    practice_name: str | None = None
    available_providers: str | None = None
    location_city: str | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: str | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    treatment_modality: str | None = None
    client_focus: str | None = None
    age_group: Literal[*CLIENT_AGE_GROUPS] | None = None
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS] | None = None
    payment_situation: Literal[*INSURANCE_OPTIONS] | None = None
    sliding_scale: bool | None = None
    cost: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "practice_name",
        "available_providers",
        "location_city",
        "client_focus",
    )
    @classmethod
    def _strip_required(cls, v: str | None) -> str | None:
        return _strip_required_or_none(v)

    @field_validator("location_zip")
    @classmethod
    def _validate_zip(cls, v: str | None) -> str | None:
        return _validate_zip_or_none(v)

    @field_validator("treatment_modality", "cost")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return _strip_optional(v)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderAvailabilityUpdate":
        _at_least_one_editable_field(self)
        return self


PostUpdate = Annotated[
    Union[ClientReferralUpdate, ProviderAvailabilityUpdate],
    Field(discriminator="kind"),
]
post_update_adapter: TypeAdapter = TypeAdapter(PostUpdate)


# --- Audit snapshots ----------------------------------------------------


class _PostAuditSnapshotBase(BaseModel):
    owner_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_post(cls, data):
        return _flatten_post_to_dict(data) or data


class ClientReferralAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["client_referral"]
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: str
    services_psychotherapy_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS]


class ProviderAvailabilityAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["provider_availability"]
    practice_name: str
    available_providers: str
    location_city: str
    location_state: Literal[*US_STATES]
    location_zip: str
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    treatment_modality: str | None = None
    client_focus: str
    age_group: Literal[*CLIENT_AGE_GROUPS]
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    payment_situation: Literal[*INSURANCE_OPTIONS]
    sliding_scale: bool
    cost: str | None = None


PostAuditSnapshot = Annotated[
    Union[
        ClientReferralAuditSnapshot,
        ProviderAvailabilityAuditSnapshot,
    ],
    Field(discriminator="kind"),
]
_post_audit_snapshot_adapter: TypeAdapter = TypeAdapter(PostAuditSnapshot)


def post_audit_snapshot(post) -> dict:
    """Build the audit `before`/`after` projection for a post of any kind.

    Validates `post` against the discriminated `PostAuditSnapshot` union
    — the `kind` discriminator picks the matching variant, which then
    flattens through the right detail relationship via the shared
    `_flatten_post_to_dict` helper. Adding a new `kind` only requires
    registering it in `REGISTERED_KINDS` and adding its `*AuditSnapshot`
    variant to the union above.
    """
    return _post_audit_snapshot_adapter.validate_python(post).model_dump(mode="json")
