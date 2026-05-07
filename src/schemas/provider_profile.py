"""Wire schemas for provider profile and its credential sub-entities.

A `ProviderProfile` is a long-lived directory entry owned by a single
`User` (1:1 via `user_id`). It holds three credential lists —
`ProviderLicensure`, `ProviderEducation`, `ProviderCertification` —
each managed via its own endpoints in later issues. The wire surface
mirrors that shape: each entity has Read / Create / Update /
AuditSnapshot variants.

`ProviderProfileRead` and `ProviderProfileAuditSnapshot` embed the
sub-entity Read / AuditSnapshot lists. `ProviderProfileUpdate` does
**not** include nested lists — sub-entities are PATCHed via their own
routes (added later), so a profile-level PATCH only touches the
practice/availability fields.

Controlled-vocabulary fields (state, license type, etc.) are typed as
`Literal[*TUPLE]` against the tuples in `src/models/post_enums.py` so
the schema's accepted values stay in lockstep with the DB CHECK
constraints. Free-text fields reuse `StrippedText` and `ZipText` from
[`src/schemas/post.py`](post.py) — defining them once means one source
of truth for the cleaning rule.

A guardrail test in `test_provider_profile.py`
(`test_schema_literals_match_model_tuples`) keeps the `Literal`
universes aligned with the source tuples.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from src.models.post_enums import (
    CERTIFICATION_TYPES,
    EDUCATION_TYPES,
    LICENSE_TYPES,
    LOCATION_AVAILABILITY_OPTIONS,
    US_STATES,
)
from src.schemas.post import StrippedText, ZipText

# --- Shared helpers -----------------------------------------------------


def _assert_any_field_set(model: BaseModel) -> None:
    """Raise `ValueError` if every field on `model` is `None`. Shared
    between the Update variants so the at-least-one-field rule lives in
    one place. Provider Update schemas have no discriminator, so all
    declared fields participate."""
    fields = type(model).model_fields
    if all(getattr(model, name) is None for name in fields):
        raise ValueError("at least one editable field must be provided")


# --- ProviderLicensure --------------------------------------------------


class ProviderLicensureRead(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderLicensureCreate(BaseModel):
    license_type: Literal[*LICENSE_TYPES]
    license_number: StrippedText
    issuing_state: Literal[*US_STATES]
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderLicensureUpdate(BaseModel):
    license_type: Literal[*LICENSE_TYPES] | None = None
    license_number: StrippedText | None = None
    issuing_state: Literal[*US_STATES] | None = None
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderLicensureUpdate":
        _assert_any_field_set(self)
        return self


class ProviderLicensureAuditSnapshot(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    license_type: str
    license_number: str
    issuing_state: str
    expiration_date: date | None = None

    model_config = ConfigDict(from_attributes=True)


# --- ProviderEducation --------------------------------------------------


class ProviderEducationRead(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    education_type: str
    institution: str
    month_completed: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderEducationCreate(BaseModel):
    education_type: Literal[*EDUCATION_TYPES]
    institution: StrippedText
    # `month_completed` is a "YYYY-MM" string per the model — month
    # precision only. Format validation is intentionally deferred to a
    # later issue once the form contract is settled.
    month_completed: str | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderEducationUpdate(BaseModel):
    education_type: Literal[*EDUCATION_TYPES] | None = None
    institution: StrippedText | None = None
    month_completed: str | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderEducationUpdate":
        _assert_any_field_set(self)
        return self


class ProviderEducationAuditSnapshot(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    education_type: str
    institution: str
    month_completed: str | None = None

    model_config = ConfigDict(from_attributes=True)


# --- ProviderCertification ----------------------------------------------


class ProviderCertificationRead(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None

    model_config = ConfigDict(from_attributes=True)


class ProviderCertificationCreate(BaseModel):
    certification_type: Literal[*CERTIFICATION_TYPES]
    certifying_body: StrippedText
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")


class ProviderCertificationUpdate(BaseModel):
    certification_type: Literal[*CERTIFICATION_TYPES] | None = None
    certifying_body: StrippedText | None = None
    expiration_date: date | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderCertificationUpdate":
        _assert_any_field_set(self)
        return self


class ProviderCertificationAuditSnapshot(BaseModel):
    id: uuid.UUID
    profile_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    certification_type: str
    certifying_body: str
    expiration_date: date | None = None

    model_config = ConfigDict(from_attributes=True)


# --- ProviderProfile ----------------------------------------------------


class ProviderProfileRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
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


class ProviderProfileCreate(BaseModel):
    """Create payload for a provider's directory profile. `user_id` is
    set by the route from the authenticated user, not accepted on the
    wire."""

    practice_name: StrippedText
    location_city: StrippedText
    location_state: Literal[*US_STATES]
    location_zip: ZipText
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS]
    licensures: list[ProviderLicensureCreate] = []
    educations: list[ProviderEducationCreate] = []
    certifications: list[ProviderCertificationCreate] = []

    model_config = ConfigDict(extra="forbid")


class ProviderProfileUpdate(BaseModel):
    """Partial update of practice/availability fields only. Sub-entity
    lists (licensures, educations, certifications) are managed via
    their own endpoints, so this schema does not accept them."""

    practice_name: StrippedText | None = None
    location_city: StrippedText | None = None
    location_state: Literal[*US_STATES] | None = None
    location_zip: ZipText | None = None
    in_person_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None
    virtual_sessions: Literal[*LOCATION_AVAILABILITY_OPTIONS] | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProviderProfileUpdate":
        _assert_any_field_set(self)
        return self


class ProviderProfileAuditSnapshot(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    practice_name: str
    location_city: str
    location_state: str
    location_zip: str
    in_person_sessions: str
    virtual_sessions: str
    licensures: list[ProviderLicensureAuditSnapshot] = []
    educations: list[ProviderEducationAuditSnapshot] = []
    certifications: list[ProviderCertificationAuditSnapshot] = []

    model_config = ConfigDict(from_attributes=True)
