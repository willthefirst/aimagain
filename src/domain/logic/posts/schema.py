"""Wire schemas for posts.

`Post` is a parent row with a `kind` discriminator and a per-kind detail
table. The wire surface mirrors that shape: `PostCreate` / `PostUpdate`
/ `PostRead` / `PostAuditSnapshot` are kind-discriminated unions on the
(required) `kind` field. The single ``/posts`` URL family uses these
union adapters directly (whole-supertype face).

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
from typing import Annotated, Literal, Union

from pydantic import (
    BeforeValidator,
    Field,
    TypeAdapter,
    model_serializer,
    model_validator,
)

from src.domain.logic.value_objects.location import (
    FlatLocationSchema,
    Location,
    LocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
)
from src.domain.models import POST_KINDS
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    DESIRED_TIME_SLOTS,
    GENDERS,
    INSURANCE_CARRIERS,
    LANGUAGES,
    LOCATION_AVAILABILITY_OPTIONS,
    NETWORK_PREFERENCES,
    REFERRAL_SERVICES,
    TREATMENT_MODALITIES,
    TREATMENT_SETTINGS,
)
from src.framework.rendering.form_fields import HtmlTextarea, HtmlUrl
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
    scalar_to_list,
)

# `description` and `referral_instructions` on `opening` are
# free-form prose long enough to want a multi-line control. The marker
# only affects form rendering (`field_for` picks `<textarea>` over
# `<input>`); the validator chain is identical to `StrippedOptionalText`.
TextareaOptional = Annotated[StrippedOptionalText, HtmlTextarea()]

# `website` is a URL with the same `Stripped` cleaning chain — the
# marker only swaps form rendering from `<input type=text>` to
# `<input type=url>`. Schema-side validation stays the same; browser
# gates submission on URL syntax client-side.
UrlOptional = Annotated[StrippedOptionalText, HtmlUrl()]


def _empty_to_none(v):
    """Coerce an empty/whitespace-only string to `None` for optional enum
    fields. HTML `<select>` with a placeholder option always submits a
    string — `""` when the user hasn't picked anything. Without this,
    Pydantic's `Literal[*TUPLE] | None` would try the `Literal` arm
    against `""`, fail, and 422 every form submission that omits the
    field. Required enum fields don't need this — `""` legitimately
    422s a required field — so it's wired up per-field, not globally."""
    if isinstance(v, str) and v.strip() == "":
        return None
    return v


OptionalInsuranceCarrier = Annotated[
    Literal[*INSURANCE_CARRIERS] | None, BeforeValidator(_empty_to_none)
]


# Annotated aliases for the multi-checkbox fields. The `BeforeValidator`
# runs first and normalizes a scalar string to a single-element list
# (see `scalar_to_list` in `framework/schema_validators.py`); `Literal[*TUPLE]` then validates each member.
DesiredTimesField = Annotated[
    list[Literal[*DESIRED_TIME_SLOTS]], BeforeValidator(scalar_to_list)
]
ServicesField = Annotated[
    list[Literal[*REFERRAL_SERVICES]], BeforeValidator(scalar_to_list)
]
# `opening.services` is required-min-1 on the wire; layer
# the constraint over the shared alias so the scalar-coercion still runs
# first. `min_length` only fires on the list arm of `T | None`, so the
# same alias works for `T` (Create/Read/AuditSnapshot) and `T | None`
# (Update — `None` means "leave unchanged"; an empty list 422s).
RequiredServicesField = Annotated[ServicesField, Field(min_length=1)]
SettingsField = Annotated[
    list[Literal[*TREATMENT_SETTINGS]], BeforeValidator(scalar_to_list)
]
# `opening.settings` is required-min-1 on the wire; same
# pattern as services.
RequiredSettingsField = Annotated[SettingsField, Field(min_length=1)]
LanguagesField = Annotated[list[Literal[*LANGUAGES]], BeforeValidator(scalar_to_list)]
# `opening.languages` is required-min-1 on the wire — every
# practice speaks at least one language, and the unfilterable "no
# languages" state is meaningless. Mirrors services / settings.
RequiredLanguagesField = Annotated[LanguagesField, Field(min_length=1)]
AgeGroupsField = Annotated[
    list[Literal[*CLIENT_AGE_GROUPS]], BeforeValidator(scalar_to_list)
]
# `opening.age_groups` is required-min-1 on the wire — every
# practice serves at least one age bucket.
RequiredAgeGroupsField = Annotated[AgeGroupsField, Field(min_length=1)]
# `opening.genders` is a multi-checkbox on the wire, same
# normalization shape as services/settings/age_groups. Empty list is
# allowed — "no restriction stated" / serves any gender.
GendersField = Annotated[list[Literal[*GENDERS]], BeforeValidator(scalar_to_list)]
ModalitiesField = Annotated[
    list[Literal[*TREATMENT_MODALITIES]], BeforeValidator(scalar_to_list)
]


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


class ReferralRead(_PostReadBase):
    kind: Literal["referral"]
    # `(city, state, zip)` modeled as a single :class:`Location` value
    # object but kept flat on the wire/JSON shape — ``_flatten_post_to_dict``
    # produces a flat dict from the ORM, ``gather_flat_location`` nests the
    # three keys, and ``flatten_location_on_dump`` reverses on dump.
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    gender: Literal[*GENDERS]
    subject: str | None = None
    description: str
    services: ServicesField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    # See :class:`ReferralCreate` for the carrier/preference split.
    network_preference: Literal[*NETWORK_PREFERENCES]
    insurance_carrier: OptionalInsuranceCarrier = None
    # FK to the Clinician the submitting user designated as referrer.
    # Nullable on the read side — rows created before this field existed
    # will have None here.
    referring_clinician_id: uuid.UUID | None = None

    # Flat-on-dump: keep ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level of JSON responses. The parent's
    # ``_flatten_post`` already calls ``gather_flat_location`` on the way in.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ClinicianOpeningRead(_PostReadBase):
    kind: Literal["clinician_opening"]
    subject: str | None = None
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    # Practice + location + delivery-format + insurance posture all live
    # on the linked Clinician (#448, #449). Read projections expose the
    # FK; templates dereference via
    # `post.opening_detail.clinician.<field>`.
    clinician_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


class ProgramIntakeRead(_PostReadBase):
    kind: Literal["program_intake"]
    subject: str | None = None
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    # FK to the Program this announcement is for. The Program's name,
    # state preference, intake window, and owning Org all live on the
    # linked row; templates dereference via
    # `post.intake_detail.program.<field>`.
    program_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


PostRead = Annotated[
    Union[ReferralRead, ClinicianOpeningRead, ProgramIntakeRead],
    Field(discriminator="kind"),
]
post_read_adapter: TypeAdapter = TypeAdapter(PostRead)


# --- Create payloads ----------------------------------------------------
#
# Free-text fields use the Annotated aliases for input cleaning; enum
# fields use `Literal[*TUPLE]`; bool/int fields are plain Python types.
# `extra="forbid"` rejects unknown fields with 422. Cross-kind field
# bleed is rejected by the discriminated union one level up.


class ReferralCreate(FlatLocationSchema, WirePayload):
    """Create payload for `kind='referral'`. Field set follows the
    client-referral intake form.

    The ``(city, state, zip)`` triple is a single :class:`Location` value
    object; form posts still send the three keys flat at the top level
    (``gather_flat_location`` rolls them into the nested block).
    """

    kind: Literal["referral"]
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    # Required min-1 on the wire. Mirrors PA's `age_groups`.
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire. Defaults to `["en"]` so the form's
    # "submit with defaults" case still validates.
    languages: RequiredLanguagesField = ["en"]
    # Gender identity of the referred client. Defaults to
    # `prefer_not_to_say` so existing form submissions that don't
    # include the field still validate; the form's <select> defaults
    # to the same value.
    gender: Literal[*GENDERS] = "prefer_not_to_say"
    subject: StrippedOptionalText = None
    description: StrippedText
    services: ServicesField = []
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField = []
    # `network_preference` is the referrer's posture toward in-network
    # match (required). `insurance_carrier` is the patient's actual
    # carrier (nullable — null means self-pay / unknown / no carrier,
    # which is the natural shape when network_preference='no_preference').
    # No cross-field validator yet: the form hides the carrier control
    # when 'no_preference' is selected, so the data-shape stays clean in
    # practice; tightening this to a server-side invariant is a separate
    # decision.
    network_preference: Literal[*NETWORK_PREFERENCES]
    insurance_carrier: OptionalInsuranceCarrier = None
    # FK to the Clinician the submitting user designates as referrer.
    # Required on new referrals; the ownership check in
    # `_assert_post_payload_target_ownership` verifies the user owns
    # the clinician before persisting.
    referring_clinician_id: uuid.UUID


class ClinicianOpeningCreate(WirePayload):
    """Create payload for `kind='clinician_opening'`. Field set follows
    the clinician-availability intake form."""

    kind: Literal["clinician_opening"]
    subject: StrippedOptionalText = None
    # Optional initially — graduates to required once seed posts confirm
    # the shape works.
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to one of the requesting user's Clinician profiles. The form
    # restricts the dropdown to clinicians owned by the user; the route
    # handler also verifies ownership at write time so a wire-level
    # attacker can't reference another user's clinician.
    clinician_id: uuid.UUID
    desired_times: DesiredTimesField = []
    # Free-text companion to `desired_times` for cohort dates / fixed
    # program hours. Single-line input; not a textarea.
    schedule_text: StrippedOptionalText = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField = []
    # Required min-1 on the wire. No default; every PA post must declare
    # at least one bucket explicitly.
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire. Defaults to `["en"]` so the form's
    # "submit with defaults" case still validates.
    languages: RequiredLanguagesField = ["en"]
    # Genders this practice serves. Optional; empty = "no restriction
    # stated" / serves any. Multi-checkbox on the wire.
    genders: GendersField = []


class ProgramIntakeCreate(WirePayload):
    """Create payload for `kind='intake'`. Field set mirrors
    :class:`ClinicianOpeningCreate` one-to-one but swaps the Clinician
    FK for a Program FK — the referrer is choosing a Program (intake door),
    not a specific clinician."""

    kind: Literal["program_intake"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to one of the requesting user's Programs. The form restricts the
    # dropdown to Programs owned by the user; the spec's `payload_authz_path`
    # verifies ownership at write time so a wire-level attacker can't
    # reference another user's Program.
    program_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: StrippedOptionalText = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField = []
    # Required min-1 on the wire — mirrors PA's age_groups.
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire — mirrors PA's languages.
    languages: RequiredLanguagesField = ["en"]
    genders: GendersField = []


PostCreate = Annotated[
    Union[ReferralCreate, ClinicianOpeningCreate, ProgramIntakeCreate],
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


class ReferralUpdate(FlatLocationSchema, PartialUpdate):
    # `kind` is the discriminator, always required on the wire; the
    # `PartialUpdate` "at least one field" rule excludes it via
    # `at_least_one_field_exclude`.
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["referral"]
    # See :class:`ReferralCreate` — flat on the wire, nested
    # value object in Python, flat on dump.
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
    subject: StrippedOptionalText = None
    description: StrippedText | None = None
    services: ServicesField | None = None
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField | None = None
    # `None` = leave unchanged; any enum value sets it. Clearing the
    # carrier back to NULL via PATCH is not supported today (matches the
    # repo's "None means leave unchanged" semantic for optional fields).
    network_preference: Literal[*NETWORK_PREFERENCES] | None = None
    insurance_carrier: OptionalInsuranceCarrier = None
    # `None` = leave unchanged. Ownership re-checked on update — a PATCH
    # that repoints to a clinician the user doesn't own is 403.
    referring_clinician_id: uuid.UUID | None = None


class ClinicianOpeningUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["clinician_opening"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to a Clinician profile owned by the requesting user. `None` =
    # leave unchanged. The route handler verifies ownership on update.
    clinician_id: uuid.UUID | None = None
    desired_times: DesiredTimesField | None = None
    schedule_text: StrippedOptionalText = None
    # `None` = leave unchanged; `min_length=1` rejects an explicit `[]`.
    # Clearing services entirely is intentionally not supported on PA —
    # the wire invariant is min-1.
    services: RequiredServicesField | None = None
    settings: RequiredSettingsField | None = None
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField | None = None
    age_groups: RequiredAgeGroupsField | None = None
    # `None` = leave unchanged. `min_length=1` rejects an explicit `[]`,
    # mirroring `services`. Clearing the list is intentionally not
    # supported.
    languages: RequiredLanguagesField | None = None
    # `None` = leave unchanged; `[]` is allowed (clear the list to
    # "no restriction stated").
    genders: GendersField | None = None


class ProgramIntakeUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["program_intake"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    referral_instructions: TextareaOptional = None
    website: UrlOptional = None
    # FK to a Program owned by the requesting user. `None` = leave
    # unchanged. The spec's `payload_authz_path` verifies ownership on
    # update too — repointing at an unowned Program is 403.
    program_id: uuid.UUID | None = None
    desired_times: DesiredTimesField | None = None
    schedule_text: StrippedOptionalText = None
    services: RequiredServicesField | None = None
    settings: RequiredSettingsField | None = None
    treatment_modality: StrippedOptionalText = None
    modalities: ModalitiesField | None = None
    age_groups: RequiredAgeGroupsField | None = None
    languages: RequiredLanguagesField | None = None
    genders: GendersField | None = None


PostUpdate = Annotated[
    Union[ReferralUpdate, ClinicianOpeningUpdate, ProgramIntakeUpdate],
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


class ReferralAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["referral"]
    # Mirrors :class:`ReferralRead`. Audit ``before`` / ``after``
    # snapshots stay flat on the wire — the serializer unrolls the nested
    # ``location`` block back to top-level keys.
    location: Location
    location_in_person: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    location_virtual: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    desired_times: DesiredTimesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    gender: Literal[*GENDERS]
    subject: str | None = None
    description: str
    services: ServicesField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    network_preference: Literal[*NETWORK_PREFERENCES]
    insurance_carrier: OptionalInsuranceCarrier = None
    referring_clinician_id: uuid.UUID | None = None

    # Flat-on-dump — see :class:`ReferralRead`.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ClinicianOpeningAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["clinician_opening"]
    subject: str | None = None
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    # Audit row records the FK, not the dereferenced practice fields —
    # standard pattern for relational audit snapshots.
    clinician_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


class ProgramIntakeAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["program_intake"]
    subject: str | None = None
    description: str | None = None
    referral_instructions: str | None = None
    website: str | None = None
    program_id: uuid.UUID
    desired_times: DesiredTimesField = []
    schedule_text: str | None = None
    services: ServicesField = []
    settings: SettingsField = []
    treatment_modality: str | None = None
    modalities: ModalitiesField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    genders: GendersField = []


PostAuditSnapshot = Annotated[
    Union[
        ReferralAuditSnapshot,
        ClinicianOpeningAuditSnapshot,
        ProgramIntakeAuditSnapshot,
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
