# Backward-compatibility shim. All view helpers have moved to
# src.domain.logic.clinicians.view.
from src.domain.logic.clinicians.view import (  # noqa: F401
    _affiliation_insurance_summary,
    _insurance_summary,
    affiliation_card_view,
    provider_card_view,
)
