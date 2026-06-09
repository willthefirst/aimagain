"""Pytest fixtures scoped to the route-test directory.

`_autouse_mock_nppes` patches NPPES to return a verified-match response
for every test under `src/domain/routes/test_*.py`. Without it, the
inline-create gate on `POST /clinicians` and `POST /organizations`
(which now raises `BadRequestError` on any non-verified NPPES outcome
— see `src/domain/logic/clinicians/handlers.py` and the verifications
README) would block the happy path in every route-level integration
test with a real NPPES round-trip.

The mock lives here, not in `tests/fixtures.py`, on purpose: making it
autouse globally would break the verification-cluster tests under
`src/domain/logic/verifications/test_handlers.py`, which exercise the
real `nppes_lookup` against a mocked HTTP transport. Pytest's conftest
discovery scopes this autouse to the directory tree the file lives in,
so the verification tests stay untouched.

The defaults align with the wire defaults used by route-level tests:
`tests.helpers.clinician_payload()` (Jane / Smith) and the org-create
tests' `_org_payload()` (Acme Health). A test that needs a failure-mode
lookup (NPI not found, name mismatch, OIG hit) re-patches the two
symbols locally with a higher-precedence `monkeypatch.setattr`.
"""

from unittest.mock import AsyncMock

import pytest

from src.domain.logic.verifications.nppes import NppesOrgResult, NppesResult


@pytest.fixture(autouse=True)
def _autouse_mock_nppes(monkeypatch):
    monkeypatch.setattr(
        "src.domain.logic.verifications.handlers.nppes_lookup",
        AsyncMock(
            return_value=NppesResult(
                found=True, first_name="Jane", last_name="Smith", raw={}
            )
        ),
    )
    monkeypatch.setattr(
        "src.domain.logic.verifications.handlers.nppes_lookup_type2",
        AsyncMock(
            return_value=NppesOrgResult(
                found=True,
                org_name="Acme Health",
                authorized_official_name=None,
                raw={},
            )
        ),
    )
