from typing import Literal

from pydantic import BaseModel, EmailStr

from src.domain.models.enums import LICENSE_TYPES, US_STATES

_LICENSE_TYPES = Literal[tuple(LICENSE_TYPES)]  # type: ignore[valid-type]
_US_STATES = Literal[tuple(US_STATES)]  # type: ignore[valid-type]


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
