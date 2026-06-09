"""Pytest fixtures scoped to the route-test directory.

`mock_nppes_default_match` (defined in `tests/fixtures.py`) is wired in
as autouse for every test under `src/domain/routes/test_*.py` so the
inline-create gate on `POST /clinicians` and `POST /organizations`
doesn't block the happy path with a real NPPES round-trip. The
verification-cluster tests under `src/domain/logic/verifications/`
exercise the real `nppes_lookup` against a mocked HTTP transport and
must not be affected — keeping the autouse scope to this directory
preserves that.
"""

import pytest


@pytest.fixture(autouse=True)
def _autouse_mock_nppes(mock_nppes_default_match):
    """Resolve the named fixture so it runs automatically for tests
    in this directory."""
    yield
