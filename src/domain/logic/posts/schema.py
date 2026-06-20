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
    ReferralLocation,
    ReferralLocationPartial,
    flatten_location_on_dump,
    gather_flat_location,
)
from src.domain.models import POST_KINDS
from src.domain.models.enums import (
    CLIENT_AGE_GROUPS,
    INSURANCE_CARRIERS,
    LANGUAGES,
    REFERRAL_SERVICES,
    SESSION_FORMATS,
    TREATMENT_SETTINGS,
)
from src.framework.rendering.form_fields import HtmlTextarea
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


# `ReferralDetail.insurance_carriers` — multi-select on the wire.
# Empty list (the default) means "no carrier specified", which is the
# natural shape when only ``accepts_private_pay`` is true on a referral.
# Symmetric to ``ClinicianAffiliation.in_network_carriers`` on the
# provider side — both ends now model the same shape (#1358 PR-e).
InsuranceCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(scalar_to_list)
]


# Annotated aliases for the multi-checkbox fields. The `BeforeValidator`
# runs first and normalizes a scalar string to a single-element list
# (see `scalar_to_list` in `framework/schema_validators.py`); `Literal[*TUPLE]` then validates each member.
ServicesField = Annotated[
    list[Literal[*REFERRAL_SERVICES]], BeforeValidator(scalar_to_list)
]
SettingsField = Annotated[
    list[Literal[*TREATMENT_SETTINGS]], BeforeValidator(scalar_to_list)
]
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
# `referral.session_format` — multi-checkbox on the wire (any subset
# of {in_person, virtual}). Empty list = "unspecified".
SessionFormatField = Annotated[
    list[Literal[*SESSION_FORMATS]], BeforeValidator(scalar_to_list)
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
    # `(city, state)` modeled as a single :class:`ReferralLocation`
    # value object but kept flat on the wire/JSON shape —
    # ``_flatten_post_to_dict`` produces a flat dict from the ORM,
    # ``gather_flat_location`` nests the two keys, and
    # ``flatten_location_on_dump`` reverses on dump.
    location: ReferralLocation
    # `session_format` is a multi-select list — any subset of
    # {in_person, virtual}. `view.py` derives the legacy
    # `in_person`/`virtual` view keys from list membership so the
    # cross-kind list/detail templates render unchanged.
    session_format: SessionFormatField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    subject: str | None = None
    description: str
    services: ServicesField = []
    # Payment paths — independent booleans the corpus treats as
    # non-mutually-exclusive. See :class:`ReferralCreate` for the
    # full rationale.
    accepts_in_network: bool = False
    accepts_private_pay: bool = False
    # Multi-select of `InsuranceCarrier` tokens — empty list = "no
    # carrier specified" (the typical shape when only private-pay is
    # accepted). Symmetric to `ClinicianAffiliation.in_network_carriers`.
    insurance_carriers: InsuranceCarriersField = []
    # FK to the Clinician the submitting user designated as referrer.
    # Nullable on the read side — rows created before this field existed
    # will have None here.
    referring_clinician_id: uuid.UUID | None = None
    # Context affiliation this referral was offered under. Nullable —
    # rows predating the column (and rows whose affiliation was later
    # deleted, `SET NULL`) read as None.
    clinician_affiliation_id: uuid.UUID | None = None

    # Flat-on-dump: keep ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level of JSON responses. The parent's
    # ``_flatten_post`` already calls ``gather_flat_location`` on the way in.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ClinicianOpeningRead(_PostReadBase):
    """Read projection for a thin opening detail row (#1358 PR-f sub-3).

    The steady-state profile fields (services / settings / modalities /
    age_groups / genders / languages / website / referral_instructions)
    moved off this row onto the linked ``ClinicianAffiliation`` /
    ``Clinician`` in PR-f. Templates dereference via
    ``post.opening_detail.clinician_affiliation.<field>`` (and
    ``.clinician.languages`` for the person-level one).
    """

    kind: Literal["clinician_opening"]
    subject: str | None = None
    description: str | None = None
    # Practice + location + delivery-format + insurance posture all live
    # on the linked Clinician (#448, #449). Read projections expose the
    # FK; templates dereference via
    # `post.opening_detail.clinician.<field>`.
    clinician_id: uuid.UUID
    # Context affiliation this opening is offered under. Nullable — see
    # `ReferralRead.clinician_affiliation_id`.
    clinician_affiliation_id: uuid.UUID | None = None
    schedule_text: str | None = None
    treatment_modality: str | None = None


class ProgramIntakeRead(_PostReadBase):
    """Read projection for a thin program-intake detail row (#1358 PR-f sub-3).

    Same shape as :class:`ClinicianOpeningRead` minus the clinician
    context — Program is the steady-state home for the intake side.
    """

    kind: Literal["program_intake"]
    subject: str | None = None
    description: str | None = None
    # FK to the Program this announcement is for. The Program's name,
    # state preference, intake window, owning Org, and steady-state
    # profile all live on the linked row; templates dereference via
    # `post.intake_detail.program.<field>`.
    program_id: uuid.UUID
    schedule_text: str | None = None
    treatment_modality: str | None = None


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

    The ``(city, state)`` pair is a single :class:`ReferralLocation`
    value object; form posts still send the two keys flat at the top
    level (``gather_flat_location`` rolls them into the nested block).
    """

    kind: Literal["referral"]
    location: ReferralLocation
    # See :class:`ReferralRead.session_format`. Multi-checkbox on the
    # wire; empty list = "unspecified".
    session_format: SessionFormatField = []
    # Required min-1 on the wire. Mirrors PA's `age_groups`.
    age_groups: RequiredAgeGroupsField
    # Required min-1 on the wire. Defaults to `["en"]` so the form's
    # "submit with defaults" case still validates.
    languages: RequiredLanguagesField = ["en"]
    subject: StrippedOptionalText = None
    description: StrippedText
    services: ServicesField = []
    # Payment paths. Independent booleans; not mutually exclusive;
    # default all-false is shape-valid (some referrers genuinely leave
    # it blank) but the form encourages picking at least one. Empty
    # `insurance_carriers` is legal even when `accepts_in_network` is
    # true (the patient may have a carrier they're trying to identify,
    # or accept any carrier the provider takes).
    accepts_in_network: bool = False
    accepts_private_pay: bool = False
    insurance_carriers: InsuranceCarriersField = []
    # Context: which ClinicianAffiliation the referring clinician acts
    # under. This is what the form's practice picker submits (one option
    # per affiliation). Required on new referrals. The server resolves
    # `referring_clinician_id` from this affiliation in
    # `_assert_post_payload_authz` — see `referring_clinician_id` below.
    clinician_affiliation_id: uuid.UUID
    # FK to the Clinician the submitting user designates as referrer.
    # NOT a form input — the picker submits `clinician_affiliation_id`
    # and the server derives this from `affiliation.clinician_id`
    # (`_assert_post_payload_authz`), then re-checks ownership of the
    # resolved clinician. Optional/None on the wire; any client-sent
    # value is overwritten by the resolved one.
    referring_clinician_id: uuid.UUID | None = None


class ClinicianOpeningCreate(WirePayload):
    """Create payload for `kind='clinician_opening'`.

    After #1358 PR-f sub-3, the steady-state practice profile fields
    (services / settings / modalities / age_groups / genders / languages
    / website / referral_instructions) are no longer part of the
    announcement payload — those live on the linked
    ``ClinicianAffiliation`` (and ``languages`` on the linked
    ``Clinician``) and are managed through the affiliation / clinician
    edit pages. The opening form collects only the announcement core
    plus the practice picker.
    """

    kind: Literal["clinician_opening"]
    subject: StrippedOptionalText = None
    # Optional initially — graduates to required once seed posts confirm
    # the shape works.
    description: TextareaOptional = None
    # Context: which ClinicianAffiliation this opening is offered under.
    # This is what the form's practice picker submits (one option per
    # affiliation). Required on new openings. The server resolves
    # `clinician_id` from `affiliation.clinician_id` in
    # `_assert_post_payload_authz`.
    clinician_affiliation_id: uuid.UUID
    # FK to the Clinician whose practice this announcement describes. NOT
    # a form input — the picker submits `clinician_affiliation_id` and
    # the server derives this from `affiliation.clinician_id`
    # (`_assert_post_payload_authz`), then re-checks ownership. Optional/
    # None on the wire; any client-sent value is overwritten.
    clinician_id: uuid.UUID | None = None
    # Free-text for cohort dates / fixed program hours. Single-line
    # input; not a textarea.
    schedule_text: StrippedOptionalText = None
    treatment_modality: StrippedOptionalText = None


class ProgramIntakeCreate(WirePayload):
    """Create payload for `kind='program_intake'`. Mirrors
    :class:`ClinicianOpeningCreate` one-to-one but swaps the Clinician
    FK for a Program FK — the referrer is choosing a Program (intake door),
    not a specific clinician. The steady-state profile lives on the
    linked ``Program`` (#1358 PR-f sub-3)."""

    kind: Literal["program_intake"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    # FK to one of the requesting user's Programs. The form restricts the
    # dropdown to Programs owned by the user; the spec's `payload_authz_path`
    # verifies ownership at write time so a wire-level attacker can't
    # reference another user's Program.
    program_id: uuid.UUID
    schedule_text: StrippedOptionalText = None
    treatment_modality: StrippedOptionalText = None


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
    location: ReferralLocationPartial | None = None
    # `None` = leave unchanged; `[]` = clear all selections. Same
    # list-replace semantics as other list fields. See
    # :class:`ReferralRead.session_format`.
    session_format: SessionFormatField | None = None
    age_groups: RequiredAgeGroupsField | None = None
    # `None` = leave unchanged. `min_length=1` rejects an explicit `[]`,
    # mirroring PA's `languages` semantics.
    languages: RequiredLanguagesField | None = None
    subject: StrippedOptionalText = None
    description: StrippedText | None = None
    services: ServicesField | None = None
    # `None` = leave unchanged; any bool sets the flag. The payment
    # paths are independent — a PATCH may flip just one or any subset
    # without disturbing the others.
    accepts_in_network: bool | None = None
    accepts_private_pay: bool | None = None
    # `None` = leave unchanged; `[]` = clear all carriers. List-valued
    # PATCH replaces the whole list — partial add/remove is intentionally
    # out of scope, matching `services`.
    insurance_carriers: InsuranceCarriersField | None = None
    # `None` = leave unchanged. The form picker submits this; the server
    # re-derives `referring_clinician_id` from it (and re-checks
    # ownership of the resolved clinician) in `_assert_post_payload_authz`.
    clinician_affiliation_id: uuid.UUID | None = None
    # `None` = leave unchanged. Server-derived from
    # `clinician_affiliation_id` when the picker changes context;
    # ownership re-checked on update — repointing to a clinician the user
    # doesn't own is 403.
    referring_clinician_id: uuid.UUID | None = None


class ClinicianOpeningUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["clinician_opening"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    # `None` = leave unchanged. The form picker submits this; the server
    # re-derives `clinician_id` from it (and re-checks ownership of the
    # resolved clinician) in `_assert_post_payload_authz`.
    clinician_affiliation_id: uuid.UUID | None = None
    # FK to a Clinician profile owned by the requesting user. `None` =
    # leave unchanged. Server-derived from `clinician_affiliation_id`
    # when the picker changes context; ownership verified on update.
    clinician_id: uuid.UUID | None = None
    schedule_text: StrippedOptionalText = None
    treatment_modality: StrippedOptionalText = None


class ProgramIntakeUpdate(PartialUpdate):
    at_least_one_field_exclude = frozenset({"kind"})

    kind: Literal["program_intake"]
    subject: StrippedOptionalText = None
    description: TextareaOptional = None
    # FK to a Program owned by the requesting user. `None` = leave
    # unchanged. The spec's `payload_authz_path` verifies ownership on
    # update too — repointing at an unowned Program is 403.
    program_id: uuid.UUID | None = None
    schedule_text: StrippedOptionalText = None
    treatment_modality: StrippedOptionalText = None


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
    location: ReferralLocation
    # See :class:`ReferralRead.session_format`.
    session_format: SessionFormatField = []
    age_groups: AgeGroupsField = []
    languages: LanguagesField = []
    subject: str | None = None
    description: str
    services: ServicesField = []
    accepts_in_network: bool = False
    accepts_private_pay: bool = False
    insurance_carriers: InsuranceCarriersField = []
    referring_clinician_id: uuid.UUID | None = None
    clinician_affiliation_id: uuid.UUID | None = None

    # Flat-on-dump — see :class:`ReferralRead`.
    @model_serializer(mode="wrap")
    def _flatten_location(self, handler):
        return flatten_location_on_dump(self, handler(self))


class ClinicianOpeningAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["clinician_opening"]
    subject: str | None = None
    description: str | None = None
    # Audit row records the FK, not the dereferenced practice fields —
    # standard pattern for relational audit snapshots.
    clinician_id: uuid.UUID
    clinician_affiliation_id: uuid.UUID | None = None
    schedule_text: str | None = None
    treatment_modality: str | None = None


class ProgramIntakeAuditSnapshot(_PostAuditSnapshotBase):
    kind: Literal["program_intake"]
    subject: str | None = None
    description: str | None = None
    program_id: uuid.UUID
    schedule_text: str | None = None
    treatment_modality: str | None = None


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
