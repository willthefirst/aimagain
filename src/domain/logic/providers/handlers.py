# Backward-compatibility shim. All handlers have moved to
# src.domain.logic.clinicians.handlers.
from src.domain.logic.clinicians.handlers import (  # noqa: F401
    _assert_clinician_payload_org_ownership,
    _assert_provider_payload_org_ownership,
    clinician_detail_extras,
    clinician_form_extras,
    handle_list_user_clinicians,
    handle_list_user_providers,
    provider_detail_extras,
    provider_form_extras,
)
