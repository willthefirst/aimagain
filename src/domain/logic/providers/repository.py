# Backward-compatibility shim. All repository logic has moved to
# src.domain.logic.clinicians.repository.
from src.domain.logic.clinicians.repository import (  # noqa: F401
    ClinicianRepository,
    ProviderRepository,
    get_clinician_repository,
    get_provider_repository,
)
