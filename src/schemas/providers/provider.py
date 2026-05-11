"""Wire schemas for provider and its credential sub-entities.

A `Provider` is a long-lived directory entry owned by a `User`
(N:1 via `owner_id` — a user may own zero, one, or many providers). It
holds three credential lists —
`ProviderLicensure`, `ProviderEducation`, `ProviderCertification` —
each managed via its own endpoints in later issues. The wire surface
mirrors that shape: each entity has Read / Create / Update variants.

`AuditSnapshot` variants are byte-identical to `Read` for every provider
schema — same fields, same `from_attributes`. Rather than declare two
classes per entity, the `*AuditSnapshot` symbols are aliases to the
`*Read` siblings. Audit-row JSON shape is unchanged. Posts and users
genuinely diverge between Read and AuditSnapshot (id omitted from the
audit row) and keep distinct classes — see those modules.

`ProviderRead` embeds the sub-entity Read lists. `ProviderUpdate` does
**not** include nested lists — sub-entities are PATCHed via their own
routes (added later), so a provider-level PATCH only touches the
practice/availability fields.

Controlled-vocabulary fields (state, license type, etc.) are typed as
`Literal[*TUPLE]` against the tuples in `src/models/enums.py` so
the schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields reuse `StrippedText` and `ZipText` from
[`src/schemas/_validators.py`](_validators.py) — defining them once
means one source of truth for the cleaning rule.

A guardrail test in `test_provider.py`
(`test_schema_literals_match_model_tuples`) keeps the `Literal`
universes aligned with the source tuples.
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict

from src.core.form_fields import HtmlPattern
from src.models.enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.schemas._validators import PartialUpdate, StrippedText, ZipText


class _ProviderSubrowBase(BaseModel):
    """Common fields for every provider sub-row Read schema (licensure /
    education / certification). Subclasses add entity-specific fields.

    The credential AuditSnapshot variants are aliases to the matching
    Read class (see module docstring); both surfaces share this base.
    """

    id: uuid.UUID
    provider_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- ProviderLicensure --------------------------------------------------


class ProviderLicensureRead(_ProviderSubrowBase):
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None


class ProviderLicensureCreate(BaseModel):
    license_type: Literal[*LICENSE_TYPES]
    license_number: StrippedText
    issuing_state: Literal[*US_STATES]
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderLicensureUpdate(PartialUpdate):
    license_type: Literal[*LICENSE_TYPES] | None = None
    license_number: StrippedText | None = None
    issuing_state: Literal[*US_STATES] | None = None
    expiration_date: date | None = None


# The provider-credential AuditSnapshots are byte-identical to their
# Read siblings — same base, same fields, same `from_attributes`. The
# alias keeps the public symbol stable for spec imports while folding
# the duplicated class into one declaration.
ProviderLicensureAuditSnapshot = ProviderLicensureRead


# --- ProviderEducation --------------------------------------------------


class ProviderEducationRead(_ProviderSubrowBase):
    education_type: str
    institution: str
    month_completed: str | None = None


class ProviderEducationCreate(BaseModel):
    education_type: Literal[*EDUCATION_TYPES]
    institution: StrippedText
    # `month_completed` is a "YYYY-MM" string per the model — month
    # precision only. Format validation is intentionally deferred to a
    # later issue once the form contract is settled.
    month_completed: str | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderEducationUpdate(PartialUpdate):
    education_type: Literal[*EDUCATION_TYPES] | None = None
    institution: StrippedText | None = None
    month_completed: str | None = None


ProviderEducationAuditSnapshot = ProviderEducationRead


# --- ProviderCertification ----------------------------------------------


class ProviderCertificationRead(_ProviderSubrowBase):
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None


class ProviderCertificationCreate(BaseModel):
    certification_type: Literal[*CERTIFICATION_TYPES]
    certifying_body: StrippedText
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderCertificationUpdate(PartialUpdate):
    certification_type: Literal[*CERTIFICATION_TYPES] | None = None
    certifying_body: StrippedText | None = None
    expiration_date: date | None = None


ProviderCertificationAuditSnapshot = ProviderCertificationRead


# --- Provider ----------------------------------------------------


class ProviderRead(BaseModel):
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

    model_config = ConfigDict(from_attributes=True)


class ProviderCreate(BaseModel):
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

    model_config = ConfigDict(extra="forbid")


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


# Provider's AuditSnapshot is byte-identical to ProviderRead once the
# credential AuditSnapshot aliases land — the nested list types collapse
# to the same classes. Alias keeps the symbol stable for the spec import.
ProviderAuditSnapshot = ProviderRead
