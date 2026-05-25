import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, field_validator

from src.domain.logic.posts.schema import (
    OptionalAvailabilityState,
    OptionalOpeningType,
    PaymentTypesField,
    PopulationTagsField,
    SpecialtiesField,
)
from src.domain.models.enums import LANGUAGES, LICENSE_TYPES, US_STATES
from src.framework.schema_validators import StrippedOptionalText, scalar_to_list

_LICENSE_TYPES = Literal[tuple(LICENSE_TYPES)]  # type: ignore[valid-type]
_US_STATES = Literal[tuple(US_STATES)]  # type: ignore[valid-type]
_LANGUAGES = Literal[tuple(LANGUAGES)]  # type: ignore[valid-type]

_SpecialtiesList = Annotated[list[str], BeforeValidator(scalar_to_list)]


class VerifyForm(BaseModel):
    """Wire schema for POST /welcome/verify.

    Collects enough data to create a Clinician + ProviderLicensure + run NPPES
    verification. `issuing_state` is required because `ProviderLicensure.issuing_state`
    is NOT NULL.
    """

    first_name: str
    last_name: str
    work_email: EmailStr
    license_type: _LICENSE_TYPES
    license_number: str
    issuing_state: _US_STATES


class FirstOpeningForm(BaseModel):
    """Wire schema for POST /welcome/first-opening.

    All slot fields are optional — the wizard encourages completion but
    never blocks on it. Field types mirror the T3 schema aliases on
    ClinicianOpeningCreate; validation rules (empty→None, scalar→list)
    are shared via those aliases.
    """

    opening_type: OptionalOpeningType = None
    specialties: SpecialtiesField = []
    population_tags: PopulationTagsField = []
    languages: list[_LANGUAGES] = []
    fee_low: int | None = None
    fee_high: int | None = None
    payment_types: PaymentTypesField = []
    availability_state: OptionalAvailabilityState = None
    colleague_note: Annotated[StrippedOptionalText, Field(max_length=280)] = None


class BeFindableForm(BaseModel):
    """Wire schema for POST /welcome/be-findable.

    Collects the clinician's practice specialties and session modality so they
    appear in referral searches. All fields optional — the wizard encourages
    completion but never blocks on it (empty submission = no-op write).

    `in_person` / `virtual` are booleans that map to Affiliation's
    `in_person_sessions` / `virtual_sessions` TEXT columns ("yes" / "no").
    """

    specialties: _SpecialtiesList = []
    in_person: bool = False
    virtual: bool = False


# ---------------------------------------------------------------------------
# PII guard — patterns that indicate a client identifier slipped into a
# clinical-context free-text field. The referral form prompts for "the
# clinical picture only", so email / US phone / proper-name patterns are
# red flags worth rejecting at the wire layer. False-positive rate is
# acceptable for this use case: the form copy explains the rule upfront.
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # US phone
    re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b"),  # Proper Name Pattern
]


class ReferralFromWizardForm(BaseModel):
    """Wire schema for POST /welcome/refer/{opening_id}.

    Collects the minimal data needed to create a Referral post pointing at a
    specific opening. PII guard on `clinical_context` rejects email addresses,
    US phone numbers, and proper-name patterns — the field is for clinical
    picture only, never client identifiers.
    """

    target_opening_id: uuid.UUID
    clinical_context: str

    @field_validator("clinical_context")
    @classmethod
    def no_pii(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Clinical context is required.")
        if len(v) > 4000:
            raise ValueError("Clinical context must be 4000 characters or fewer.")
        for pat in _PII_PATTERNS:
            if pat.search(v):
                raise ValueError(
                    "Please remove client name / contact info — describe the clinical picture only."
                )
        return v
