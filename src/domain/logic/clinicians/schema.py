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

`ClinicianRead` embeds the sub-entity Read lists. `ClinicianUpdate` is
**person-level only** (`first_name`, `last_name`, `npi`): practice
posture (location, availability, insurance, cost, `org_id`) lives on
`ClinicianAffiliation` — same person can hold different posture per
practice context — so it is patched via that entity's own endpoint
(`PATCH /clinicians/{id}/clinician_affiliations/{aff_id}`). Sub-entity
lists (licensures, educations, certifications) similarly manage
themselves under their own URLs.

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
)
from src.domain.models.enums import (
    AFFIRMING_IDENTITIES,
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_TYPES,
    US_STATES,
)
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedText,
    WirePayload,
    clean_free_form_tags,
    scalar_to_list,
)

# Affirming-identity multi-checkbox field — multi-value JSON list of
# `AFFIRMING_IDENTITIES` tokens. Mirrors the multi-checkbox idiom posts
# use (see `domain/logic/posts/schema.py`): a single string from a form
# checkbox is normalized to a one-element list before validation.
AffirmingIdentitiesField = Annotated[
    list[Literal[*AFFIRMING_IDENTITIES]], BeforeValidator(scalar_to_list)
]

# Clinical-niche tags — free-form vocabulary on the provider side
# (#1358 PR-c). Symmetric to `ReferralDetail.clinical_niches`.
# Deliberately NOT an enum: the corpus vocabulary ("DGBI", "ADHD in
# women", "psychedelic-knowledgeable", "complex trauma") is too
# open-ended to commit to `Literal[*ENUM]` on day one; promote heavily-
# used tags later. `clean_free_form_tags` strips, drops empties, and
# deduplicates.
ClinicalNichesField = Annotated[list[str], BeforeValidator(clean_free_form_tags)]

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
    # Affirming-identity claims. JSON list of `AFFIRMING_IDENTITIES`
    # tokens; person-level (lives directly on the clinician, not on an
    # affiliation). Empty list = "none stated".
    affirming_identities: AffirmingIdentitiesField = []
    # Clinical-niche claims — free-form tag list. Empty list = no
    # niches stated. See `ClinicalNichesField` for the simplicity
    # rationale (tagged free-text now; promote to enum later).
    clinical_niches: ClinicalNichesField = []
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


class ClinicianUpdate(PartialUpdate):
    """Partial update of the **person-level** fields on a Clinician —
    name and NPI. Practice posture (location, availability, insurance,
    cost, org) lives on :class:`ClinicianAffiliation` because the same
    person can hold different posture per practice context, so it is
    edited via the affiliation's own ``PATCH /clinicians/{id}/clinician_affiliations/{aff_id}``
    endpoint, not here. Sub-entity lists (licensures, educations,
    certifications) similarly manage themselves under their own URLs.

    Empty input on ``first_name`` / ``last_name`` raises a 422 (cannot
    clear to NULL); absent fields pass through ``exclude_unset=True``
    and don't touch the persisted value. ``npi`` accepts a 10-digit
    string or blank → ``None`` (clears).
    """

    npi: NpiText = None
    first_name: StrippedText | None = None
    last_name: StrippedText | None = None
    # `None` = leave unchanged (the repo's standard partial-update
    # semantic); `[]` = clear all claims. List-valued PATCH replaces the
    # whole list — partial add/remove is intentionally out of scope.
    affirming_identities: AffirmingIdentitiesField | None = None
    # Same partial-update semantics as `affirming_identities` above:
    # `None` = leave unchanged, `[]` = clear all tags, list = replace.
    clinical_niches: ClinicalNichesField | None = None


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
