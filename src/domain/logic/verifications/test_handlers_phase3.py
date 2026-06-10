"""Phase-3 pipeline tests for the verification cluster:

- `run_org_verification(...)` — Type-2 NPPES pipeline, mocked via
  `httpx.MockTransport`.
- `nppes_lookup_type2(...)` directly — fixture-driven happy path +
  not-found path + wrong-enumeration-type defensive return.

`run_clinician_verification` side-effects on `Clinician.clinician_verified`
+ `verified_at` + `ever_verified_at` are also pinned here (Phase 3 added
the cache write-through; the existing handler-tests file pins the row
shape but not the side effects).

The recompute helpers and `record_verification_event` moved to
`test_events.py` — those tests don't need HTTP mocks or LEIE fixtures.
"""

import json
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications import oig as oig_module
from src.domain.logic.verifications.handlers import (
    run_clinician_verification,
    run_org_verification,
)
from src.domain.logic.verifications.nppes import nppes_lookup_type2
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    Organization,
)
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
)

# `pytest.mark.asyncio` applied per-async-function rather than at module
# scope — the cache write-through test seeds data synchronously first.


@pytest.fixture(autouse=True)
def _leie_path_env(monkeypatch, tmp_path):
    """Point OIG at an empty CSV so the run_*_verification pipelines
    here aren't affected by a real LEIE fixture. Cache reset between
    tests."""
    empty_csv = tmp_path / "leie_empty.csv"
    empty_csv.write_text("FIRSTNAME,LASTNAME,NPI,EXCLDATE,REINDATE,EXCLTYPE\n")
    monkeypatch.setenv("LEIE_CSV_PATH", str(empty_csv))
    oig_module._reset_cache_for_tests()
    yield
    oig_module._reset_cache_for_tests()


def _mock_http(responses: dict[str, dict[str, Any] | int]) -> httpx.AsyncClient:
    """Same `_mock_http` shape as `test_handlers.py`. Keys are NPIs;
    values are JSON payloads or status codes."""

    def handler(request: httpx.Request) -> httpx.Response:
        npi = request.url.params.get("number")
        canned = responses.get(npi or "")
        if canned is None:
            return httpx.Response(404)
        if isinstance(canned, int):
            return httpx.Response(canned)
        return httpx.Response(200, content=json.dumps(canned).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _type2_payload(
    *,
    org_name: str,
    ao_first: str = "",
    ao_last: str = "",
) -> dict[str, Any]:
    """Mock NPPES Type-2 response. Mirrors the real payload's shape:
    `enumeration_type='NPI-2'` + `basic.organization_name` +
    `basic.authorized_official_*` triplet."""
    return {
        "results": [
            {
                "enumeration_type": "NPI-2",
                "basic": {
                    "organization_name": org_name,
                    "authorized_official_first_name": ao_first,
                    "authorized_official_last_name": ao_last,
                },
            }
        ]
    }


# ---------- run_org_verification -----------------------------------------


async def test_run_org_verification_writes_through_cache(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Happy path: NPPES name matches → row persists with `status=
    'verified'`, the org's denorm cache flips to verified, and
    `authorized_official_name` is cached."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id, name="Acme Clinic")
    org.npi = "1234567890"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    http = _mock_http(
        {
            "1234567890": _type2_payload(
                org_name="Acme Clinic", ao_first="Jane", ao_last="Doe"
            )
        }
    )
    async with db_test_session_manager() as session:
        async with http:
            verification = await run_org_verification(
                org_id=org.id,
                verification_repo=VerificationRepository(session),
                org_repo=OrganizationRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, org.id)
        assert loaded.npi_match_status == "matched"
        assert loaded.org_verified is True
        assert loaded.verified_at is not None
        assert loaded.authorized_official_name == "Jane Doe"

    assert verification.status == "verified"
    assert verification.subject_type == "organization"
    assert verification.org_id == org.id


async def test_run_org_verification_needs_review_on_name_mismatch(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    org = make_organization_row(owner_id=user.id, name="Acme Clinic")
    org.npi = "1234567890"
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    http = _mock_http(
        {"1234567890": _type2_payload(org_name="Totally Different Practice")}
    )
    async with db_test_session_manager() as session:
        async with http:
            verification = await run_org_verification(
                org_id=org.id,
                verification_repo=VerificationRepository(session),
                org_repo=OrganizationRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "needs_review"
    async with db_test_session_manager() as session:
        loaded = await session.get(Organization, org.id)
        assert loaded.org_verified is False


# ---------- nppes_lookup_type2 -------------------------------------------


async def test_nppes_lookup_type2_returns_org_and_ao():
    http = _mock_http(
        {"1234567890": _type2_payload(org_name="Acme", ao_first="Jane", ao_last="Doe")}
    )
    async with http:
        result = await nppes_lookup_type2("1234567890", http=http)
    assert result.found is True
    assert result.org_name == "Acme"
    assert result.authorized_official_name == "Jane Doe"


async def test_nppes_lookup_type2_handles_404():
    http = _mock_http({"1234567890": 404})
    async with http:
        result = await nppes_lookup_type2("1234567890", http=http)
    assert result.found is False
    assert result.org_name is None


async def test_nppes_lookup_type2_rejects_type1_record():
    """Defensive: if NPPES returns a Type-1 record despite the filter,
    treat it as not-found for org purposes (don't accidentally write
    a Type-1 person's name onto the org's verification row)."""
    payload = {
        "results": [
            {
                "enumeration_type": "NPI-1",
                "basic": {"organization_name": "Should not be used"},
            }
        ]
    }
    http = _mock_http({"1234567890": payload})
    async with http:
        result = await nppes_lookup_type2("1234567890", http=http)
    assert result.found is False


# ---------- run_clinician_verification cache write-through ---------------


async def test_run_clinician_verification_writes_through_cache(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The pipeline writes `npi_match_status='matched'` +
    `clinician_verified=True` when the NPPES name match scores
    `verified`. Licensures are not required — a solo clinician with a
    matched NPI is fully verified."""
    owner = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            # Seed unverified so the pipeline exercises the
            # `False → True` transition. The helper defaults to
            # verified, so override here.
            clinician = make_clinician_with_org(
                owner_id=owner.id,
                npi="1234567890",
                first_name="Eva",
                last_name="Stone",
                clinician_verified=False,
                npi_match_status="none",
            )
            session.add(clinician)
    clinician_id = clinician.id

    http = _mock_http(
        {
            "1234567890": {
                "results": [{"basic": {"first_name": "Eva", "last_name": "Stone"}}]
            }
        }
    )
    async with db_test_session_manager() as session:
        async with http:
            await run_clinician_verification(
                clinician_id=clinician_id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    async with db_test_session_manager() as session:
        loaded = await session.get(Clinician, clinician_id)
        assert loaded.npi_match_status == "matched"
        assert loaded.clinician_verified is True
        assert loaded.verified_at is not None
        assert loaded.ever_verified_at is not None
