"""Phase-3 tests for the verification cluster extension:

- `recompute_clinician_claim(clinician)` — pure function: Claim-A cache
  recompute from `npi_match_status` + active licensures.
- `recompute_org_claim(org)` — pure function: Claim-B prereq cache from
  `npi_match_status`.
- `record_verification_event(...)` — append-only writer for the non-NPPES
  §9 transitions (license_attested / authority_proven / admin_verify /
  etc.) with the matching audit row.
- `run_org_verification(...)` — Type-2 NPPES pipeline, mocked via
  `httpx.MockTransport`.
- `nppes_lookup_type2(...)` directly — fixture-driven happy path +
  not-found path + wrong-enumeration-type defensive return.

`run_clinician_verification` side-effects on `Clinician.clinician_verified`
+ `verified_at` + `ever_verified_at` are also pinned here (Phase 3 added
the cache write-through; the existing handler-tests file pins the row
shape but not the side effects).
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.verifications import oig as oig_module
from src.domain.logic.verifications.handlers import (
    recompute_clinician_claim,
    recompute_org_claim,
    record_verification_event,
    run_clinician_verification,
    run_org_verification,
)
from src.domain.logic.verifications.nppes import nppes_lookup_type2
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import (
    Clinician,
    ClinicianLicensure,
    Organization,
    Verification,
)
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
)

# `pytest.mark.asyncio` applied per-async-function rather than at module
# scope — half the tests here are pure synchronous functions
# (`recompute_*_claim`) and would warn under a blanket pytestmark.


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


# ---------- recompute_clinician_claim ------------------------------------


def test_recompute_clinician_claim_requires_matched_npi_and_active_license():
    """Matched NPI without any active license → False."""
    clinician = Clinician(
        id=uuid4(),
        owner_id=uuid4(),
        npi="1234567890",
        first_name="Eva",
        last_name="Stone",
    )
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = False
    clinician.licensures = [
        ClinicianLicensure(
            clinician_id=clinician.id,
            license_type="lcsw",
            license_number="X-1",
            issuing_state="IL",
            status="pending",
        )
    ]
    recompute_clinician_claim(clinician)
    assert clinician.clinician_verified is False


def test_recompute_clinician_claim_active_license_without_matched_npi_false():
    """Active license without matched NPI → False."""
    clinician = Clinician(
        id=uuid4(), owner_id=uuid4(), first_name="Eva", last_name="Stone"
    )
    clinician.npi_match_status = "pending"
    clinician.clinician_verified = False
    clinician.licensures = [
        ClinicianLicensure(
            clinician_id=clinician.id,
            license_type="lcsw",
            license_number="X-1",
            issuing_state="IL",
            status="active",
        )
    ]
    recompute_clinician_claim(clinician)
    assert clinician.clinician_verified is False


def test_recompute_clinician_claim_happy_path():
    clinician = Clinician(
        id=uuid4(),
        owner_id=uuid4(),
        npi="1234567890",
        first_name="Eva",
        last_name="Stone",
    )
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = False
    clinician.verified_at = None
    clinician.ever_verified_at = None
    clinician.licensures = [
        ClinicianLicensure(
            clinician_id=clinician.id,
            license_type="lcsw",
            license_number="X-1",
            issuing_state="IL",
            status="active",
        )
    ]
    recompute_clinician_claim(clinician)
    assert clinician.clinician_verified is True
    assert clinician.verified_at is not None
    assert clinician.ever_verified_at is not None


def test_recompute_clinician_claim_preserves_ever_verified_at_on_regression():
    """A clinician who was previously verified and now isn't (license
    expired) must keep `ever_verified_at` set — that's what the
    `can_read_full_feed` retention rule reads."""
    historic = datetime(2025, 6, 1, tzinfo=timezone.utc)
    clinician = Clinician(id=uuid4(), owner_id=uuid4())
    clinician.npi_match_status = "matched"
    clinician.clinician_verified = True
    clinician.verified_at = historic
    clinician.ever_verified_at = historic
    clinician.licensures = [
        ClinicianLicensure(
            clinician_id=clinician.id,
            license_type="lcsw",
            license_number="X-1",
            issuing_state="IL",
            status="expired",
        )
    ]
    recompute_clinician_claim(clinician)
    assert clinician.clinician_verified is False
    assert clinician.ever_verified_at == historic


# ---------- recompute_org_claim ------------------------------------------


def test_recompute_org_claim_matched_flips_true():
    org = Organization(
        id=uuid4(),
        owner_id=uuid4(),
        name="Acme",
        type="clinic",
        root_org_id=uuid4(),
    )
    org.npi_match_status = "matched"
    org.org_verified = False
    org.verified_at = None
    recompute_org_claim(org)
    assert org.org_verified is True
    assert org.verified_at is not None


def test_recompute_org_claim_pending_keeps_false():
    org = Organization(
        id=uuid4(),
        owner_id=uuid4(),
        name="Acme",
        type="clinic",
        root_org_id=uuid4(),
    )
    org.npi_match_status = "pending"
    org.org_verified = False
    recompute_org_claim(org)
    assert org.org_verified is False


def test_recompute_org_claim_regression_clears_verified():
    org = Organization(
        id=uuid4(),
        owner_id=uuid4(),
        name="Acme",
        type="clinic",
        root_org_id=uuid4(),
    )
    org.npi_match_status = "mismatch"  # admin closed a soft mismatch
    org.org_verified = True
    recompute_org_claim(org)
    assert org.org_verified is False


# ---------- record_verification_event ------------------------------------


async def _seed_clinician_only(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> Clinician:
    owner = create_test_user(username=f"owner-{uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clinician = make_clinician_with_org(owner_id=owner.id, npi="1234567890")
            session.add(clinician)
    return clinician


async def _seed_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> Organization:
    user = create_test_user(username=f"orgowner-{uuid4()}")
    org = make_organization_row(owner_id=user.id, name="Acme")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
    return org


async def test_record_event_clinician_appends_row_and_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician = await _seed_clinician_only(db_test_session_manager)
    async with db_test_session_manager() as session:
        verification = await record_verification_event(
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            subject_type="clinician",
            clinician_id=clinician.id,
            event_type="license_attested",
            evidence={"license_id": "X-1"},
            actor_id=None,
        )
        await session.commit()

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].event_type == "license_attested"
        assert rows[0].evidence == {"license_id": "X-1"}

        audits = (
            (
                await session.execute(
                    select(AuditLog).filter(AuditLog.resource_id == verification.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1


async def test_record_event_org_appends_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    org = await _seed_org(db_test_session_manager)
    async with db_test_session_manager() as session:
        await record_verification_event(
            verification_repo=VerificationRepository(session),
            audit_repo=AuditRepository(session),
            subject_type="organization",
            org_id=org.id,
            event_type="authority_proven",
            actor_id=None,
        )
        await session.commit()

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(Verification.org_id == org.id)
                )
            )
            .scalars()
            .first()
        )
        assert row.event_type == "authority_proven"
        assert row.subject_type == "organization"
        assert row.clinician_id is None


async def test_record_event_xor_check(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Passing both `clinician_id` and `org_id` (or neither) is a
    handler-level misuse — fail loudly in Python before the DB check
    fires."""
    clinician = await _seed_clinician_only(db_test_session_manager)
    org = await _seed_org(db_test_session_manager)
    async with db_test_session_manager() as session:
        with pytest.raises(ValueError, match="exactly one"):
            await record_verification_event(
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                subject_type="clinician",
                clinician_id=clinician.id,
                org_id=org.id,
                event_type="admin_verify",
                actor_id=None,
            )
        with pytest.raises(ValueError, match="exactly one"):
            await record_verification_event(
                verification_repo=VerificationRepository(session),
                audit_repo=AuditRepository(session),
                subject_type="clinician",
                event_type="admin_verify",
                actor_id=None,
            )


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
    """After Phase 3, the pipeline writes `npi_match_status='matched'`
    + `clinician_verified=True` when the score is `verified` AND the
    clinician has an active license. Without an active license the
    cache stays False even after a successful NPPES match."""
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

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                ClinicianLicensure(
                    clinician_id=clinician_id,
                    license_type="lcsw",
                    license_number="X-1",
                    issuing_state="IL",
                    status="active",
                )
            )

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
