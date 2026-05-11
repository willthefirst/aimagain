"""Wire schemas for posts.

`Post` is a parent row with a `kind` discriminator and a per-kind detail
table. The wire surface mirrors that shape: `PostCreate` / `PostUpdate`
/ `PostRead` / `PostAuditSnapshot` are kind-discriminated unions on the
(required) `kind` field.

`post_audit_snapshot(post)` validates a SQLAlchemy `Post` against the
union and returns a JSON-mode dump for the audit row.

The per-kind detail relationship + fields live in
[`src/models/posts/post_kinds.py`](../models/posts/post_kinds.py) — this module's
`_flatten_post_to_dict` reads from that registry. Adding a kind here
means the four Pydantic variant classes (Read/Create/Update/
AuditSnapshot) plus their entry in the discriminated unions; everything
else flows from the registry.

Controlled-vocabulary fields (state, age group, etc.) are typed as
`Literal[*TUPLE]` against tuples in `src/models/enums.py` so the
schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields (city, ZIP, descriptions, optional
modality strings) use the `StrippedText`, `ZipText`, and
`StrippedOptionalText` aliases from
[`src/framework/schema_validators.py`](_validators.py) so the cleaning rule
lives in one place and attaches to the field type rather than
per-class `@field_validator` methods. The Update variants reuse the
same aliases as `T | None`; Pydantic skips the AfterValidator on the
`None` arm, so one alias covers required and optional flavors.

Two guardrail tests in `test_post.py` keep enums in lockstep:
`test_schema_literals_match_model_tuples` (Literal universes match the
tuples) and `test_labels_cover_their_tuples` (every value has a
display label).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import (
    BeforeValidator,
    Field,
    TypeAdapter,
    model_validator,
)

from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
    ZipText,
)
from src.models import POST_KINDS
from src.models.enums import (
    CLIENT_AGE_GROUPS,
    CLIENT_REFERRAL_SERVICES,
    DESIRED_TIME_SLOTS,
    INSURANCE_OPTIONS,
    LANGUAGE_PREFERRED_OPTIONS,
    LOCATION_AVAILABILITY_OPTIONS,
    TREATMENT_SETTINGS,
    US_STATES,
)


def _scalar_to_list(v):
    """Wrap a single string in a one-element list. HTML form posts collapse
    a 1-checkbox-checked group to a scalar (htmx's `json-enc` only emits
    an array when the same name appears 2+ times); this normalizes that
    1-element case before the `Literal[*TUPLE]` member check fires. The
    0-element case is handled by the field default `[]`; the 2+ case
    already arrives as a list. Reused by every multi-checkbox field
    (`desired_times`, `services`, and the upcoming `settings`)."""
    if isinstance(v, str):
        return [v]
    return v


# Annotated aliases for the multi-checkbox fields. The `BeforeValidator`
# runs first and normalizes a scalar string to a single-element list
# (see `_scalar_to_list`); `Literal[*TUPLE]` then validates each member.
DesiredTimesField = Annotated[
    list[Literal[*DESIRED_TIME_SLOTS]], BeforeValidator(_scalar_to_list)
]
ServicesField = Annotated[
    list[Literal[*CLIENT_REFERRAL_SERVICES]], BeforeValidator(_scalar_to_list)
]
# `provider_availability.services` is required-min-1 on the wire; layer
# the constraint over the shared alias so the scalar-coercion still runs
# first. `min_length` only fires on the list arm of `T | None`, so the
# same alias works for `T` (Create/Read/AuditSnapshot) and `T | None`
# (Update — `None` means "leave unchanged"; an empty list 422s).
RequiredServicesField = Annotated[ServicesField, Field(min_length=1)]
SettingsField = Annotated[
    list[Literal[*TREATMENT_SETTINGS]], BeforeValidator(_scalar_to_list)
]
# `provider_availability.settings` is required-min-1 on the wire; same
# pattern as services.
RequiredSettingsField = Annotated[SettingsField, Field(min_length=1)]


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
    both shapes. Per-kind metadata comes from `POST_KINDS`.
    """
    kind = getattr(post, "kind", None)
    spec = POST_KINDS.get(kind)
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


class _PostReadBase(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

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
    desired_times: DesiredTimesField = []
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: str
    services: ServicesField = []
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
    desired_times: DesiredTimesField = []
    # Read does not enforce min-1 — pre-services PA rows backfilled to
    # `[]` by the migration would otherwise be unreadable. Min-1 lives
    # on Create/Update only, where it actually prevents new violations.
    services: ServicesField = []
    settings: SettingsField = []
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
#
# Free-text fields use the Annotated aliases for input cleaning; enum
# fields use `Literal[*TUPLE]`; bool/int fields are plain Python types.
# `extra="forbid"` rejects unknown fields with 422. Cross-kind field
# bleed is rejected by the discriminated union one level up.


class ClientReferralCreate(WirePayload):
    """Create payload for `kind='client_referral'`. Field set follows the
    client-referral intake form."""

    kind: Literal["client_referral"]
    location_city: StrippedText
    location_state: Literal[*US_STATES]
    location_zip: ZipText
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: StrippedText
    services: ServicesField = []
    services_psychotherapy_modality: StrippedOptionalText = None
    insurance: Literal[*INSURANCE_OPTIONS]


class ProviderAvailabilityCreate(WirePayload):
    """Create payload for `kind='provider_availability'`. Field set follows
    the provider-availability intake form."""

    kind: Literal["provider_availability"]
    practice_name: StrippedText
    available_providers: StrippedText
    location_city: StrippedText
    location_state: Literal[*US_STATES]
    location_zip: ZipText
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    # Required min-1 on PA per spec — divergence from CR's optional
    # `services`. No default: an absent field 422s, an empty list 422s.
    services: RequiredServicesField
    settings: RequiredSettingsField
    treatment_modality: StrippedOptionalText = None
    client_focus: StrippedText
    age_group: Literal[*CLIENT_AGE_GROUPS]
    # Optional + default per spec — provider form's "non-English services"
    # is asymmetric with the client form's `language_preferred` (required,
    # also defaults to "no"). Both default to "no"; only the
    # required-ness differs.
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS] = "no"
    payment_situation: Literal[*INSURANCE_OPTIONS]
    sliding_scale: bool
    cost: StrippedOptionalText = None


PostCreate = Annotated[
    Union[ClientReferralCreate, ProviderAvailabilityCreate],
    Field(discriminator="kind"),
]
post_create_adapter: TypeAdapter = TypeAdapter(PostCreate)


# --- Update payloads (partial) ------------------------------------------
#
# Every per-kind editable field is `T | None = None` and the
# at-least-one-field rule is enforced in a model validator. Fields
# whose value is `None` are interpreted as "leave unchanged" by
# `PostRepository.update_post`. Optional free-text fields can therefore
# only be *set* via PATCH today, not cleared back to `None`; that's a
# pre-existing repository semantic and intentionally out of scope here.
#
# The Annotated cleaning aliases attach to the non-`None` arm of the
# union, so e.g. `StrippedText | None` strips and validates a provided
# string but leaves `None` untouched — same alias works for both
# Create and Update.


class ClientReferralUpdate(PartialUpdate):
    # `kind` is the discriminator, always required on the wire; the
    # `PartialUpdate` "at least one field" rule excludes it via
    # `at_least_one_field_exclude`.
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["client_referral"]
    location_city: StrippedText | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: ZipText | None = None
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    # `None` = leave unchanged (per `update_post`); `[]` = clear all
    # selections. List-valued PATCH replaces the whole list — partial
    # add/remove is intentionally out of scope.
    desired_times: DesiredTimesField | None = None
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS] | None = None
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS] | None = None
    description: StrippedText | None = None
    services: ServicesField | None = None
    services_psychotherapy_modality: StrippedOptionalText = None
    insurance: Literal[*INSURANCE_OPTIONS] | None = None


class ProviderAvailabilityUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["provider_availability"]
    practice_name: StrippedText | None = None
    available_providers: StrippedText | None = None
    location_city: StrippedText | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: ZipText | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    desired_times: DesiredTimesField | None = None
    # `None` = leave unchanged; `min_length=1` rejects an explicit `[]`.
    # Clearing services entirely is intentionally not supported on PA —
    # the wire invariant is min-1.
    services: RequiredServicesField | None = None
    settings: RequiredSettingsField | None = None
    treatment_modality: StrippedOptionalText = None
    client_focus: StrippedText | None = None
    age_group: Literal[*CLIENT_AGE_GROUPS] | None = None
    non_english_services: Literal[*LANGUAGE_PREFERRED_OPTIONS] | None = None
    payment_situation: Literal[*INSURANCE_OPTIONS] | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None


PostUpdate = Annotated[
    Union[ClientReferralUpdate, ProviderAvailabilityUpdate],
    Field(discriminator="kind"),
]
post_update_adapter: TypeAdapter = TypeAdapter(PostUpdate)


# --- Audit snapshots ----------------------------------------------------


class _PostAuditSnapshotBase(ReadProjection):
    owner_id: uuid.UUID

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
    desired_times: DesiredTimesField = []
    client_dem_ages: Literal[*CLIENT_AGE_GROUPS]
    language_preferred: Literal[*LANGUAGE_PREFERRED_OPTIONS]
    description: str
    services: ServicesField = []
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
    desired_times: DesiredTimesField = []
    # AuditSnapshot mirrors Read — no min-1 enforcement, so historic /
    # backfilled rows can be projected without 422-ing the audit pipeline.
    services: ServicesField = []
    settings: SettingsField = []
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
    registering it in `POST_KINDS` and adding its `*AuditSnapshot`
    variant to the union above.
    """
    return _post_audit_snapshot_adapter.validate_python(post).model_dump(mode="json")
