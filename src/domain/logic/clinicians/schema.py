"""Wire schemas for the clinician entity and its credential sub-entities.

A `Clinician` is a long-lived directory entry owned by a `User`
(N:1 via `owner_id` — a user may own zero, one, or many clinicians). It
holds three credential lists —
`ClinicianLicensure`, `ClinicianEducation`, `ClinicianCertification` —
each managed via its own endpoints in later issues. The wire surface
mirrors that shape: each entity has Read / Create / Update variants.

Audit snapshots for every clinician entity are byte-identical to the
matching `Read` schema, so each `EntitySpec` reads its audit shape
through `read_schema` directly — `EntitySpec.__post_init__` defaults
`audit_snapshot` to `read_schema` when the latter is a Pydantic class.
This module therefore declares no `*AuditSnapshot` symbols; posts and
users genuinely diverge (kind-discriminated flatten / omitted id) and
keep distinct classes — see those modules.

`ClinicianRead` embeds the sub-entity Read lists. `ClinicianUpdate` does
**not** include nested lists — sub-entities are PATCHed via their own
routes (added later), so a clinician-level PATCH only touches the
practice/availability fields.

Controlled-vocabulary fields (state, license type, etc.) are typed as
`Literal[*TUPLE]` against the tuples in `src/domain/models/enums.py` so
the schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields reuse `StrippedText` and `ZipText` from
[`src/framework/schema_validators.py`](_validators.py) — defining them once
means one source of truth for the cleaning rule.

A guardrail test in `test_schema.py`
(`test_schema_literals_match_model_tuples`) keeps the `Literal`
universes aligned with the source tuples.
"""

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator

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


def _validate_required_npi(v: str | None) -> str:
    cleaned = _validate_npi(v)
    if cleaned is None:
        raise ValueError("NPI is required")
    return cleaned


# NPI is a National Provider Identifier — 10 ASCII digits. The HTML
# `pattern` hint mirrors the validator so the form's `<input>` rejects
# bad values client-side too. Also imported by `OrganizationCreate` (the
# org's Type-2 NPI); stays here as the single definition until a third
# consumer justifies hoisting to `framework/schema_validators`.
NpiText = Annotated[
    str | None,
    AfterValidator(_validate_npi),
    HtmlPattern(pattern=r"\d{10}", maxlength=10),
]

# Required flavor: blank/None input 422s with "NPI is required". Used by
# Create schemas where the wire-side gate must reject missing NPIs.
RequiredNpiText = Annotated[
    str,
    AfterValidator(_validate_required_npi),
    HtmlPattern(pattern=r"\d{10}", maxlength=10),
]


# `in_network_carriers` is a multi-checkbox group; scalar→singleton coercion
# matches the pattern shared with PA/CR multi-select fields.
InNetworkCarriersField = Annotated[
    list[Literal[*INSURANCE_CARRIERS]], BeforeValidator(scalar_to_list)
]


class _ClinicianSubrowBase(ReadProjection):
    """Common fields for every credential sub-row Read schema (licensure /
    education / certification). Subclasses add entity-specific fields.
    Also serves as the audit-snapshot shape (see module docstring).

    Credentials FK to `clinicians.id` — they're person-level data shared
    across affiliations. The wire surface carries `clinician_id` (the
    persisted FK); the URL scopes mutations through
    `/clinicians/{clinician_id}/...`.
    """

    id: uuid.UUID
    clinician_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- ClinicianLicensure -------------------------------------------------


class ClinicianLicensureRead(_ClinicianSubrowBase):
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None


class ClinicianLicensureCreate(WirePayload):
    license_type: Literal[*LICENSE_TYPES]
    license_number: StrippedText
    issuing_state: Literal[*US_STATES]
    expiration_date: date | None = None


class ClinicianLicensureUpdate(PartialUpdate):
    license_type: Literal[*LICENSE_TYPES] | None = None
    license_number: StrippedText | None = None
    issuing_state: Literal[*US_STATES] | None = None
    expiration_date: date | None = None


# --- ClinicianEducation -------------------------------------------------


class ClinicianEducationRead(_ClinicianSubrowBase):
    education_type: str
    institution: str
    month_completed: str | None = None


class ClinicianEducationCreate(WirePayload):
    education_type: Literal[*EDUCATION_TYPES]
    institution: StrippedText
    # `month_completed` is a "YYYY-MM" string per the model — month
    # precision only. Format validation is intentionally deferred to a
    # later issue once the form contract is settled.
    month_completed: str | None = None


class ClinicianEducationUpdate(PartialUpdate):
    education_type: Literal[*EDUCATION_TYPES] | None = None
    institution: StrippedText | None = None
    month_completed: str | None = None


# --- ClinicianCertification ---------------------------------------------


class ClinicianCertificationRead(_ClinicianSubrowBase):
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None


class ClinicianCertificationCreate(WirePayload):
    certification_type: Literal[*CERTIFICATION_TYPES]
    certifying_body: StrippedText
    expiration_date: date | None = None


class ClinicianCertificationUpdate(PartialUpdate):
    certification_type: Literal[*CERTIFICATION_TYPES] | None = None
    certifying_body: StrippedText | None = None
    expiration_date: date | None = None


# --- Clinician ----------------------------------------------------


class ClinicianRead(FlatLocationSchema, ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    # Affiliation-derived fields are optional: a newly-created clinician
    # has no `ClinicianAffiliation` until one is added via the affiliation
    # sub-resource. Org assignment, location, availability, and insurance
    # posture all live on `ClinicianAffiliation`; the proxy properties on
    # `Clinician` return `None` (or `[]` for `in_network_carriers`) when
    # there's no primary affiliation.
    org_id: uuid.UUID | None = None
    org_name: str | None = None
    # National Provider Identifier; 10 ASCII digits. Required at create
    # time; the column is `nullable=True` only so legacy rows without NPI
    # remain readable.
    npi: str | None = None
    # Legal first / last name — required on the model (NOT NULL).
    first_name: str
    last_name: str
    # `(city, state, zip)` arrive flat — from ORM attributes via
    # ``from_attributes`` or from a flat dict — and dump flat (JSON
    # responses still expose ``location_city`` / ``location_state`` /
    # ``location_zip`` at the top level). ``gather_flat_location`` rolls
    # the flat input into a nested ``location`` block before validation
    # so the ``Location`` value object owns the cleaning rules; the
    # ``@model_serializer`` below unrolls it back to flat on dump.
    location: Location | None = None
    in_person_sessions: str | None = None
    virtual_sessions: str | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: list[str] = []
    sliding_scale: bool | None = None
    cost: str | None = None
    licensures: list[ClinicianLicensureRead] = []
    educations: list[ClinicianEducationRead] = []
    certifications: list[ClinicianCertificationRead] = []


class ClinicianCreate(WirePayload):
    """Create payload for a clinician directory entry. `owner_id` is set
    by the route from the authenticated user, not accepted on the wire.

    Minimal by design — only the person-level identifiers needed to
    bring a row into existence. Practice/affiliation fields (org, location,
    availability, insurance) are added later via the affiliation
    sub-resource on the edit page; credentials are added via their own
    endpoints.
    """

    # Legal first / last name — required; empty input fails validation.
    first_name: StrippedText
    last_name: StrippedText
    # National Provider Identifier — required at create; blank input 422s.
    npi: RequiredNpiText


class ClinicianUpdate(FlatLocationSchema, PartialUpdate):
    """Partial update of practice/availability fields only. Sub-entity
    lists (licensures, educations, certifications) are managed via
    their own endpoints, so this schema does not accept them.

    Like :class:`ClinicianCreate`, the location triple is embedded as a
    :class:`LocationPartial` value object — patches can touch one
    subfield independently (e.g. just ``location_city``) and the
    flatten-on-dump serializer keeps ``payload.model_dump(exclude_unset=True)``
    producing the same flat ``location_city`` shape the dispatch
    handler's ``repo.patch(target, **fields)`` call expects.
    """

    # Patch the Clinician's Organization by pointing `org_id` at a
    # different row in `organizations`. `org.name` changes by editing
    # the Organization itself, not via this schema.
    org_id: uuid.UUID | None = None
    # Patch the NPI by writing a 10-digit string or empty (→ `None`,
    # clearing the field). Same validator as :class:`ClinicianCreate`.
    npi: NpiText = None
    # Patch the linked Clinician's first / last name. Empty input raises
    # a 422 (cannot clear to NULL); absent fields pass through
    # `exclude_unset=True` and don't touch the persisted value.
    first_name: StrippedText | None = None
    last_name: StrippedText | None = None
    location: LocationPartial | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    accepts_out_of_network: bool | None = None
    in_network_carriers: InNetworkCarriersField | None = None
    sliding_scale: bool | None = None
    cost: StrippedOptionalText = None


# --- Admin verification-state axis ---------------------------------------


class ClinicianVerificationStateUpdate(BaseModel):
    """Body for `PUT /clinicians/{id}/verification` — admin override of
    `npi_match_status`.

    `matched` — admin accepts; the Claim-A cache is recomputed from
    licensures.
    `mismatch` — admin rejects definitively.
    `pending` — admin clears the result so the next user-driven NPI
    submit re-runs NPPES cleanly (`npi_verified_at` is also cleared so
    the fresh attempt isn't gated on the stale timestamp).

    `none` is intentionally NOT in the vocab — admin shouldn't be able
    to flip a row to "never submitted" via this axis (the column reads
    as the user's own state and `none` would mis-represent that).
    """

    state: Literal["matched", "mismatch", "pending"]


class ClinicianVerificationAuditSnapshot(ReadProjection):
    """Audit `before`/`after` for the `/clinicians/{id}/verification`
    axis. Captures only the column the axis mutates."""

    npi_match_status: str
