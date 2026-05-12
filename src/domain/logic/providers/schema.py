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

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from src.domain.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.framework.rendering.form_fields import HtmlPattern
from src.framework.schema_validators import (
    PartialUpdate,
    ReadProjection,
    StrippedText,
    WirePayload,
    ZipText,
)


class _ProviderSubrowBase(ReadProjection):
    """Common fields for every provider sub-row Read schema (licensure /
    education / certification). Subclasses add entity-specific fields.
    Also serves as the audit-snapshot shape (see module docstring).
    """

    id: uuid.UUID
    provider_id: uuid.UUID
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


class ProviderRead(ReadProjection):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    practice_name: str
    location_city: str
    location_state: str
    location_zip: str
    in_person_sessions: str
    virtual_sessions: str
    licensures: list[ProviderLicensureRead] = []
    educations: list[ProviderEducationRead] = []
    certifications: list[ProviderCertificationRead] = []


class ProviderCreate(WirePayload):
    """Create payload for a provider's directory provider. `owner_id` is
    set by the route from the authenticated user, not accepted on the
    wire."""

    # `HtmlPattern(maxlength=...)` is a form-side hint only — does not
    # affect server-side validation. It exists so the rendered
    # `<input maxlength=...>` matches the previous hand-rolled form
    # without restating the number per template. Adding a true server-
    # side length cap (`pydantic.StringConstraints` etc.) is a separate
    # concern.
    practice_name: Annotated[StrippedText, HtmlPattern(maxlength=200)]
    location_city: Annotated[StrippedText, HtmlPattern(maxlength=120)]
    location_state: Literal[*US_STATES]
    location_zip: ZipText
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    licensures: list[ProviderLicensureCreate] = []
    educations: list[ProviderEducationCreate] = []
    certifications: list[ProviderCertificationCreate] = []


class ProviderUpdate(PartialUpdate):
    """Partial update of practice/availability fields only. Sub-entity
    lists (licensures, educations, certifications) are managed via
    their own endpoints, so this schema does not accept them."""

    practice_name: StrippedText | None = None
    location_city: StrippedText | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: ZipText | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
