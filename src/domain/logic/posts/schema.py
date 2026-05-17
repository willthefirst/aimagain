"""Wire schemas for posts.

`Post` is a parent row with a `kind` discriminator and a per-kind detail
table. The wire surface mirrors that shape: `PostCreate` / `PostUpdate`
/ `PostRead` / `PostAuditSnapshot` are kind-discriminated unions on the
(required) `kind` field.

`post_audit_snapshot(post)` validates a SQLAlchemy `Post` against the
union and returns a JSON-mode dump for the audit row.

The per-kind detail relationship + fields live in
[`src/domain/models/posts/post_kinds.py`](../models/posts/post_kinds.py) — this module's
`_flatten_post_to_dict` reads from that registry. Adding a kind here
means the four Pydantic variant classes (Read/Create/Update/
AuditSnapshot) plus their entry in the discriminated unions; everything
else flows from the registry.

Controlled-vocabulary fields (state, age group, etc.) are typed as
`Literal[*TUPLE]` against tuples in `src/domain/models/enums.py` so the
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
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BeforeValidator,
    Field,
    TypeAdapter,
    model_serializer,
    model_validator,
)

from src.domain.logic.value_objects.location import (
    Location,
    LocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
)
from src.domain.models import POST_KINDS
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    CLIENT_REFERRAL_SERVICES,
    DESIRED_TIME_SLOTS,
    GENDERS,
    INSURANCE_OPTIONS,
    LANGUAGES,
    LOCATION_AVAILABILITY_OPTIONS,
    TREATMENT_SETTINGS,
)
from src.framework.rendering.form_fields import HtmlTextarea, HtmlUrl
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
)

# `description` and `referral_instructions` on `provider_availability` are
# free-form prose long enough to want a multi-line control. The marker
# only affects form rendering (`field_for` picks `<textarea>` over
# `<input>`); the validator chain is identical to `StrippedOptionalText`.
TextareaOptional = Annotated[StrippedOptionalText, HtmlTextarea()]

# `website` is a URL with the same `Stripped` cleaning chain — the
# marker only swaps form rendering from `<input type=text>` to
# `<input type=url>`. Schema-side validation stays the same; browser
# gates submission on URL syntax client-side.
UrlOptional = Annotated[StrippedOptionalText, HtmlUrl()]


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
LanguagesField = Annotated[list[Literal[*LANGUAGES]], BeforeValidator(_scalar_to_list)]
# `provider_availability.languages` is required-min-1 on the wire — every
# practice speaks at least one language, and the unfilterable "no
# languages" state is meaningless. Mirrors services / settings.
RequiredLanguagesField = Annotated[LanguagesField, Field(min_length=1)]
AgeGroupsField = Annotated[
    list[Literal[*CLIENT_AGE_GROUPS]], BeforeValidator(_scalar_to_list)
]
# `provider_availability.age_groups` is required-min-1 on the wire — every
# practice serves at least one age bucket. Replaces the single-valued
# `age_group` (#430).
RequiredAgeGroupsField = Annotated[AgeGroupsField, Field(min_length=1)]
# `provider_availability.genders` is a multi-checkbox on the wire, same
# normalization shape as services/settings/age_groups. Empty list is
# allowed — "no restriction stated" / serves any gender.
GendersField = Annotated[list[Literal[*GENDERS]], BeforeValidator(_scalar_to_list)]


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
        return gather_flat_location(_flatten_post_to_dict(data) or data)


class ClientReferralRead(_PostReadBase):
    kind: Literal["client_referral"]
    # `(city, state, zip)` modeled as a single :class:`Location` value
    # object (#451) but kept flat on the wire/JSON shape for backward
    # compatibility — ``_flatten_post_to_dict`` produces a flat dict
    # from the ORM, ``gather_flat_location`` then nests the three keys,
    # and ``flatten_location_on_dump`` reverses on dump.
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    gender: Literal[*GENDERS]
    description: str
    services: ServicesField = []
    treatment_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS]

    # Flat-on-dump: keep ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level of JSON responses (#451). The
    # parent's ``_flatten_post`` already calls ``gather_flat_location``
    # on the way in.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ProviderAvailabilityRead(_PostReadBase):
    kind: Literal["provider_availability"]
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    # Practice + location + delivery-format + insurance posture all live
    # on the linked Provider (#448, #449). Read projections expose the
    # FK; templates dereference via
    # `post.provider_availability_detail.provider.<field>`.
    provider_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


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
    client-referral intake form.

    The ``(city, state, zip)`` triple is a single :class:`Location` value
    object (#451); form posts still send the three keys flat at the top
    level (``gather_flat_location`` rolls them into the nested block).
    """

    kind: Literal["client_referral"]
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    # Required min-1 on the wire — replaces the old single-valued
    # `client_dem_ages` (#432). Mirrors PA's `age_groups` (#430).
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire — replaces the old yes/no
    # `language_preferred` flag (#428). Defaults to `["en"]` so the
    # form's "submit with defaults" case still validates.
    languages: RequiredLanguagesField = ["en"]
    # Gender identity of the referred client. Defaults to
    # `prefer_not_to_say` so existing form submissions that don't
    # include the field still validate; the form's <select> defaults
    # to the same value.
    gender: Literal[*GENDERS] = "prefer_not_to_say"
    description: StrippedText
    services: ServicesField = []
    treatment_modality: StrippedOptionalText = None
    insurance: Literal[*INSURANCE_OPTIONS]

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location_cr_create(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ProviderAvailabilityCreate(WirePayload):
    """Create payload for `kind='provider_availability'`. Field set follows
    the provider-availability intake form."""

    kind: Literal["provider_availability"]
    # Optional initially — graduates to required in a later issue once
    # seed posts confirm the shape works (#422).
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to one of the requesting user's Provider profiles. The form
    # restricts the dropdown to providers owned by the user; the route
    # handler also verifies ownership at write time so a wire-level
    # attacker can't reference another user's provider (#448).
    provider_id: uuid.UUID
    desired_times: DesiredTimesField = []
    # Free-text companion to `desired_times` for cohort dates / fixed
    # program hours (#442). Single-line input; not a textarea.
    schedule_text: StrippedOptionalText = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: StrippedOptionalText = None
    # Required min-1 on the wire — replaces the old single-valued
    # `age_group` (#430). No default; every PA post must declare at
    # least one bucket explicitly.
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire — replaces the old yes/no
    # `non_english_services` flag (#425). Defaults to `["en"]` so the
    # form's "submit with defaults" case still validates.
    languages: RequiredLanguagesField = ["en"]
    # Genders this practice serves. Optional; empty = "no restriction
    # stated" / serves any. Multi-checkbox on the wire.
    genders: GendersField = []


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
    # See :class:`ClientReferralCreate` — flat on the wire, nested
    # value object in Python, flat on dump (#451).
    location: LocationPartial | None = None
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    # `None` = leave unchanged (per `update_post`); `[]` = clear all
    # selections. List-valued PATCH replaces the whole list — partial
    # add/remove is intentionally out of scope.
    desired_times: DesiredTimesField | None = None
    age_groups: RequiredAgeGroupsField | None = None
    # `None` = leave unchanged. `min_length=1` rejects an explicit `[]`,
    # mirroring PA's `languages` semantics.
    languages: RequiredLanguagesField | None = None
    # `None` = leave unchanged; any enum value sets it.
    gender: Literal[*GENDERS] | None = None
    description: StrippedText | None = None
    services: ServicesField | None = None
    treatment_modality: StrippedOptionalText = None
    insurance: Literal[*INSURANCE_OPTIONS] | None = None

    @model_validator(mode="before")
    @classmethod
    def _gather_flat_location_cr_update(cls, data: Any) -> Any:
        return gather_flat_location(data)

    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ProviderAvailabilityUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["provider_availability"]
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to a Provider profile owned by the requesting user. `None` =
    # leave unchanged. The route handler verifies ownership on update.
    provider_id: uuid.UUID | None = None
    desired_times: DesiredTimesField | None = None
    schedule_text: StrippedOptionalText = None
    # `None` = leave unchanged; `min_length=1` rejects an explicit `[]`.
    # Clearing services entirely is intentionally not supported on PA —
    # the wire invariant is min-1.
    services: RequiredServicesField | None = None
    settings: RequiredSettingsField | None = None
    treatment_modality: StrippedOptionalText = None
    age_groups: RequiredAgeGroupsField | None = None
    # `None` = leave unchanged. `min_length=1` rejects an explicit `[]`,
    # mirroring `services`. Clearing the list is intentionally not
    # supported.
    languages: RequiredLanguagesField | None = None
    # `None` = leave unchanged; `[]` is allowed (clear the list to
    # "no restriction stated").
    genders: GendersField | None = None


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
        return gather_flat_location(_flatten_post_to_dict(data) or data)


class ClientReferralAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["client_referral"]
    # Mirrors :class:`ClientReferralRead` (#451). Audit ``before`` /
    # ``after`` snapshots stay flat on the wire — the serializer
    # unrolls the nested ``location`` block back to top-level keys.
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    gender: Literal[*GENDERS]
    description: str
    services: ServicesField = []
    treatment_modality: str | None = None
    insurance: Literal[*INSURANCE_OPTIONS]

    # Flat-on-dump (#451) — see :class:`ClientReferralRead`.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ProviderAvailabilityAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["provider_availability"]
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    # Audit row records the FK, not the dereferenced practice fields —
    # standard pattern for relational audit snapshots.
    provider_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


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
