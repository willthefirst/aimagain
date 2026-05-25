from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from src.domain.logic.posts.schema import (
    OptionalAvailabilityState,
    OptionalOpeningType,
    PaymentTypesField,
    PopulationTagsField,
    SpecialtiesField,
)
from src.domain.models.enums import LANGUAGES, LICENSE_TYPES, US_STATES
from src.framework.schema_validators import StrippedOptionalText

_LICENSE_TYPES = Literal[tuple(LICENSE_TYPES)]  # type: ignore[valid-type]
_US_STATES = Literal[tuple(US_STATES)]  # type: ignore[valid-type]
_LANGUAGES = Literal[tuple(LANGUAGES)]  # type: ignore[valid-type]


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
