# Backward-compatibility shim. All schemas have moved to
# src.domain.logic.clinicians.schema.
from src.domain.logic.clinicians.schema import (  # noqa: F401
    ProviderCertificationCreate,
    ProviderCertificationRead,
    ProviderCertificationUpdate,
    ProviderCreate,
    ProviderEducationCreate,
    ProviderEducationRead,
    ProviderEducationUpdate,
    ProviderLicensureCreate,
    ProviderLicensureRead,
    ProviderLicensureUpdate,
    ProviderRead,
    ProviderUpdate,
)
