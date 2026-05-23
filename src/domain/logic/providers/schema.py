"""Wire schemas for provider and its credential sub-entities.

A `Provider` is a long-lived directory entry owned by a `User`
(N:1 via `owner_id` — a user may own zero, one, or many providers). It
holds three credential lists —
`ProviderLicensure`, `ProviderEducation`, `ProviderCertification` —
each managed via its own endpoints in later issues. The wire surface
mirrors that shape: each entity has Read / Create / Update variants.

Audit snapshots for every provider entity are byte-identical to the
matching `Read` schema, so each `EntitySpec` reads its audit shape
through `read_schema` directly — `EntitySpec.__post_init__` defaults
`audit_snapshot` to `read_schema` when the latter is a Pydantic class.
This module therefore declares no `*AuditSnapshot` symbols; posts and
users genuinely diverge (kind-discriminated flatten / omitted id) and
keep distinct classes — see those modules.

`ProviderRead` embeds the sub-entity Read lists. `ProviderUpdate` does
**not** include nested lists — sub-entities are PATCHed via their own
routes (added later), so a provider-level PATCH only touches the
practice/availability fields.

Controlled-vocabulary fields (state, license type, etc.) are typed as
`Literal[*TUPLE]` against the tuples in `src/domain/models/enums.py` so
the schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields reuse `StrippedText` and `ZipText` from
[`src/framework/schema_validators.py`](_validators.py) — defining them once
means one source of truth for the cleaning rule.

A guardrail test in `test_provider.py`
(`test_schema_literals_match_model_tuples`) keeps the `Literal`
universes aligned with the source tuples.
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from src.domain.logic.value_objects.location import (
    FlatLocationSchema,
    Location,
    LocationPartial,
)
from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    INSURANCE_CARRIERS,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedOptionalText,
    StrippedText,
    WirePayload,
    scalar_to_list,
)

_NPI_RE = re.compile(r"^[0-9]{10}$")


def _validate_npi(v: str | None) -> str | None:
    """Accept exactly 10 ASCII digits, normalize whitespace and the
    empty string to ``None``. NPI's CHECK constraint at the DB layer
    enforces the same shape; this validator is the wire-side gate so
    bad input 422s before it reaches a transaction.
    """
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return None
    if not _NPI_RE.match(v):
        raise ValueError("must be a 10-digit NPI")
    return v


# NPI is a National Provider Identifier — 10 ASCII digits. The HTML
# `pattern` hint mirrors the validator so the form's `<input>` rejects
# bad values client-side too. Local to this module because only the
# provider entity has the column (rule-of-three).
NpiText = Annotated[
    str | None,
    AfterValidator(_validate_npi),
    HtmlPattern(pattern=r"\d{10}", maxlength=10),
]


# `in_network_carriers` is a multi-checkbox group; scalar→singleton coercion
# matches the pattern shared with PA/CR multi-select fields.
InNetworkCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(scalar_to_list)
]


class _ProviderSubrowBase(ReadProjection):
    """Common fields for every provider sub-row Read schema (licensure /
    education / certification). Subclasses add entity-specific fields.
    Also serves as the audit-snapshot shape (see module docstring).

    Credentials FK to `clinicians.id` after #635 PR A — they're person-
    level data shared across affiliations. The wire surface carries
    `clinician_id` (the persisted FK); the URL still scopes mutations
    through `/clinicians/{clinician_id}/...` so clients use the URL
    for the clinician context (URL family renamed in #642 PR 4; the
    model class stays `Provider`).
    """

    id: uuid.UUID
    clinician_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- ProviderLicensure --------------------------------------------------


class ProviderLicensureRead(_ProviderSubrowBase):
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None


class ProviderLicensureCreate(WirePayload):
    license_type: Literal[*LICENSE_TYPES]
    license_number: StrippedText
    issuing_state: Literal[*US_STATES]
    expiration_date: date | None = None


class ProviderLicensureUpdate(PartialUpdate):
    license_type: Literal[*LICENSE_TYPES] | None = None
    license_number: StrippedText | None = None
    issuing_state: Literal[*US_STATES] | None = None
    expiration_date: date | None = None


# --- ProviderEducation --------------------------------------------------


class ProviderEducationRead(_ProviderSubrowBase):
    education_type: str
    institution: str
    month_completed: str | None = None


class ProviderEducationCreate(WirePayload):
    education_type: Literal[*EDUCATION_TYPES]
    institution: StrippedText
    # `month_completed` is a "YYYY-MM" string per the model — month
    # precision only. Format validation is intentionally deferred to a
    # later issue once the form contract is settled.
    month_completed: str | None = None


class ProviderEducationUpdate(PartialUpdate):
    education_type: Literal[*EDUCATION_TYPES] | None = None
    institution: StrippedText | None = None
    month_completed: str | None = None


# --- ProviderCertification ----------------------------------------------


class ProviderCertificationRead(_ProviderSubrowBase):
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None


class ProviderCertificationCreate(WirePayload):
    certification_type: Literal[*CERTIFICATION_TYPES]
    certifying_body: StrippedText
    expiration_date: date | None = None


class ProviderCertificationUpdate(PartialUpdate):
    certification_type: Literal[*CERTIFICATION_TYPES] | None = None
    certifying_body: StrippedText | None = None
    expiration_date: date | None = None


# --- Provider ----------------------------------------------------


class ProviderRead(FlatLocationSchema, ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # `org_name` is the practice's display name, sourced from
    # ``provider.org.name`` via the model-validator below — every reader
    # (templates, audit snapshots, contract tests) reads `org_name` rather
    # than dereferencing the relationship inline.
    org_id: uuid.UUID
    org_name: str
    # National Provider Identifier; 10 ASCII digits or `None`. Used by the
    # verification pipeline to look up the provider in NPPES. No UNIQUE
    # constraint at the DB layer yet.
    npi: str | None = None
    # Legal first / last name — surfaced via `from_attributes` through
    # `Provider.first_name` / `last_name`, which proxy to the linked
    # `Clinician` (the actual column owner). Optional on read because
    # backfill is operator-driven.
    first_name: str | None = None
    last_name: str | None = None
    # `(city, state, zip)` arrive flat — from ORM attributes via
    # ``from_attributes`` or from a flat dict — and dump flat (JSON
    # responses still expose ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level). ``gather_flat_location`` rolls
    # the flat input into a nested ``location`` block before validation
    # so the ``Location`` value object owns the cleaning rules; the
    # ``@model_serializer`` below unrolls it back to flat on dump.
    location: Location
    in_person_sessions: str
    virtual_sessions: str
    accepts_out_of_network: bool
    in_network_carriers: list[str] = []
    sliding_scale: bool
    cost: str | None = None
    licensures: list[ProviderLicensureRead] = []
    educations: list[ProviderEducationRead] = []
    certifications: list[ProviderCertificationRead] = []


class ProviderCreate(FlatLocationSchema, WirePayload):
    """Create payload for a provider's directory provider. `owner_id` is
    set by the route from the authenticated user, not accepted on the
    wire.

    The ``(city, state, zip)`` location triple is modeled as a single
    :class:`Location` value object. On the wire it stays flat — form posts
    and JSON bodies send ``location_city`` / ``location_state`` /
    ``location_zip`` at the top level — the ``gather_flat_location``
    pre-validator rolls those keys into a nested ``location`` block, and
    the ``@model_serializer`` flattens the dump back to flat keys so JSON
    responses, ORM-hydrating ``model_dump()``, and audit snapshots keep
    the flat shape.
    """

    # `solo_practice=True` lets a new user skip the separate Org-create
    # step: the create handler auto-creates a solo-practice Org and
    # patches `org_id` before persisting the Provider (#699). Excluded
    # from model_dump() so the field never leaks into the ORM constructor.
    solo_practice: bool = Field(default=False, exclude=True)
    # Required when `solo_practice=False`; the handler fills it in for
    # the solo path. The `@model_validator` below enforces the invariant.
    org_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _require_org_or_solo(self) -> "ProviderCreate":
        if not self.solo_practice and self.org_id is None:
            raise ValueError("org_id is required unless solo_practice is True")
        return self

    # Optional on create; backfill is operator-driven. Empty input
    # normalizes to `None` so an unfilled form field doesn't 422.
    npi: NpiText = None
    # Legal first / last name — both optional, both normalize empty
    # string to `None` via `StrippedOptionalText` so an unfilled form
    # field doesn't persist `""`. Forwarded to the linked Clinician
    # via `Provider.__init__`'s kwarg peeling.
    first_name: StrippedOptionalText = None
    last_name: StrippedOptionalText = None
    location: Location
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    # Insurance posture. `in_network_carriers` is the set the practice
    # accepts in-network (empty = no in-network); `accepts_out_of_network`
    # is independent and defaults `True` (most practices accept OON;
    # opt-out is the explicit choice). No cross-field invariant.
    accepts_out_of_network: bool = True
    in_network_carriers: InNetworkCarriersField = []
    sliding_scale: bool = False
    cost: StrippedOptionalText = None
    licensures: list[ProviderLicensureCreate] = []
    educations: list[ProviderEducationCreate] = []
    certifications: list[ProviderCertificationCreate] = []


class ProviderUpdate(FlatLocationSchema, PartialUpdate):
    """Partial update of practice/availability fields only. Sub-entity
    lists (licensures, educations, certifications) are managed via
    their own endpoints, so this schema does not accept them.

    Like :class:`ProviderCreate`, the location triple is embedded as a
    :class:`LocationPartial` value object — patches can touch one
    subfield independently (e.g. just ``location_city``) and the
    flatten-on-dump serializer keeps ``payload.model_dump(exclude_unset=True)``
    producing the same flat ``location_city`` shape the dispatch
    handler's ``repo.patch(target, **fields)`` call expects.
    """

    # Patch the Provider's Organization by pointing `org_id` at a
    # different row in `organizations`. `org.name` changes by editing
    # the Organization itself, not via this schema.
    org_id: uuid.UUID | None = None
    # Patch the NPI by writing a 10-digit string or empty (→ `None`,
    # clearing the field). Same validator as :class:`ProviderCreate`.
    npi: NpiText = None
    # Patch the linked Clinician's first / last name. Empty input
    # normalizes to `None` so submitting a blank field clears the
    # column; absent fields pass through `exclude_unset=True` and
    # don't touch the persisted value.
    first_name: StrippedOptionalText = None
    last_name: StrippedOptionalText = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None
