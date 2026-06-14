"""Tests for the verification orchestrator.

`run_clinician_verification` is exercised with a mocked `httpx.AsyncClient`
(via `httpx.MockTransport`) and a controlled LEIE fixture pointed at
via `LEIE_CSV_PATH`. The table-driven outcome test pins one assertion
per status branch (`verified` / `needs_review` / `failed-via-NPPES` /
`failed-via-OIG` / `nppes_skipped`); the audit-row and commit
assertions live in dedicated tests so a single regression is easy to
read.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.verifications import oig as oig_module
from src.domain.logic.verifications.handlers import (
    VERIFICATION_RESOURCE,
    run_clinician_verification,
)
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Clinician, User, Verification
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import NotFoundError
from tests.helpers import create_test_user, make_clinician_with_org

pytestmark = pytest.mark.asyncio

_LEIE_FIXTURE = Path(__file__).parent / "test_data" / "leie_sample.csv"


@pytest.fixture(autouse=True)
def _leie_path_env(monkeypatch):
    """Point the OIG module at the local fixture for every test. Cache
    is cleared between tests so a path-swap test (none here, but
    future ones) sees a fresh load."""
    monkeypatch.setenv("LEIE_CSV_PATH", str(_LEIE_FIXTURE))
    oig_module._reset_cache_for_tests()
    yield
    oig_module._reset_cache_for_tests()


def _mock_http(responses: dict[str, dict[str, Any] | int]) -> httpx.AsyncClient:
    """Build a mocked `httpx.AsyncClient` whose handler returns
    `responses[npi]` for each request — either a JSON dict (→ 200) or
    an int status code (→ that status with empty body).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        npi = request.url.params.get("number")
        canned = responses.get(npi or "")
        if canned is None:
            return httpx.Response(404, text="unknown NPI in test stub")
        if isinstance(canned, int):
            return httpx.Response(canned)
        return httpx.Response(200, content=json.dumps(canned).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _nppes_basic_payload(*, first: str, last: str) -> dict[str, Any]:
    return {
        "results": [
            {
                "basic": {"first_name": first, "last_name": last},
            }
        ]
    }


async def _seed_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    npi: str | None = None,
    username: str = "owner",
    first_name: str = "Jane",
    last_name: str = "Smith",
) -> tuple[Clinician, User]:
    owner = create_test_user(username=f"{username}-{uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clinician = make_clinician_with_org(
                owner_id=owner.id,
                npi=npi,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(clinician)
    return clinician, owner


# --- Status outcomes ----------------------------------------------------


async def test_run_returns_verified_when_clinician_name_matches_nppes(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When the clinician's first/last_name match NPPES' return, the
    similarity scorer clears threshold → `verified`. Pins the
    `_clinician_names` path that reads through to the linked Clinician
    instead of the historical username fallback (which scored too low
    to ever verify)."""
    clinician, _ = await _seed_clinician(
        db_test_session_manager,
        npi="1234567890",
        first_name="Eva",
        last_name="Stone",
    )
    http = _mock_http({"1234567890": _nppes_basic_payload(first="Eva", last="Stone")})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "verified"
    assert verification.oig_match is False
    assert verification.name_match_score is not None
    assert verification.name_match_score >= 0.9, (
        f"expected high similarity on exact-name match, got "
        f"{verification.name_match_score}"
    )


async def test_run_returns_needs_review_when_nppes_name_differs(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """NPPES returns a name unrelated to the username → similarity is
    below threshold → `needs_review`. Confirms the orchestrator wires
    NPPES + scoring correctly."""
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1234567890")
    http = _mock_http(
        {"1234567890": _nppes_basic_payload(first="Bartholomew", last="Jenkins")}
    )

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "needs_review"
    assert "nppes_name_mismatch" in verification.flags
    assert verification.oig_match is False
    assert verification.name_match_score is not None
    assert verification.nppes_result is not None


async def test_run_returns_failed_when_nppes_not_found(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="9999999999")
    http = _mock_http({"9999999999": {"results": []}})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "failed"
    assert verification.flags == ["nppes_npi_not_found"]
    assert verification.name_match_score is None


async def test_run_returns_failed_when_oig_npi_match(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The LEIE fixture lists NPI `1111111111` (`EXCLUDED, ALICE`). OIG
    is a hard disqualifier — even if NPPES would succeed, the row is
    `failed` with an `oig_excluded:npi_match` flag."""
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1111111111")
    http = _mock_http(
        {"1111111111": _nppes_basic_payload(first="Doesnt", last="Matter")}
    )

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "failed"
    assert verification.flags == ["oig_excluded:npi_match"]
    assert verification.oig_match is True


async def test_run_skips_nppes_when_clinician_has_no_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`clinician.npi is None` → NPPES is not called and the row flags
    `nppes_skipped`. The orchestrator still produces a row (scoring
    routes "NPPES not found" → `failed` with the usual NPPES flag, plus
    the skip flag at the front)."""
    clinician, _ = await _seed_clinician(db_test_session_manager, npi=None)
    http = _mock_http({})  # no NPPES calls expected

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "failed"
    assert "nppes_skipped" in verification.flags
    assert "nppes_npi_not_found" in verification.flags
    assert verification.nppes_result is None


# --- Audit + commit -----------------------------------------------------


async def test_run_writes_one_audit_row_with_create_action(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1234567890")
    http = _mock_http({"1234567890": _nppes_basic_payload(first="X", last="Y")})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_type == VERIFICATION_RESOURCE.type,
                        AuditLog.resource_id == verification.id,
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].action == "create_verification"
    assert rows[0].before is None
    assert rows[0].after is not None
    assert rows[0].after["status"] == verification.status
    assert rows[0].actor_id is None  # system-triggered run


async def test_run_persists_a_committed_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The orchestrator commits before returning. A fresh session in
    another connection must see the row."""
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1234567890")
    http = _mock_http({"1234567890": _nppes_basic_payload(first="X", last="Y")})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )
        verification_id: UUID = verification.id

    async with db_test_session_manager() as fresh:
        row = await fresh.get(Verification, verification_id)
        assert row is not None
        assert row.clinician_id == clinician.id


async def test_run_records_actor_id_when_provided(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Superuser retrigger flow: `actor_id` is the admin's id, not
    `None`."""
    admin = create_test_user(username=f"admin-{uuid4()}", is_superuser=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(admin)
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1234567890")
    http = _mock_http({"1234567890": _nppes_basic_payload(first="X", last="Y")})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=admin.id,
            )

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_id == verification.id,
                    )
                )
            )
            .scalars()
            .first()
        )
    assert row is not None
    assert row.actor_id == admin.id


async def test_run_raises_not_found_for_missing_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    http = _mock_http({})
    bogus = uuid4()

    async with db_test_session_manager() as session:
        async with http:
            with pytest.raises(NotFoundError):
                await run_clinician_verification(
                    clinician_id=bogus,
                    verification_repo=VerificationRepository(session),
                    clinician_repo=ClinicianRepository(session),
                    audit_repo=AuditRepository(session),
                    http=http,
                    actor_id=None,
                )


async def test_run_short_circuits_on_dev_magic_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    """`ENVIRONMENT=development` + `npi=0000000000` (the magic string)
    bypasses NPPES entirely and lands on `verified`. The mocked
    `httpx.AsyncClient` is configured to fail any actual call so the
    test pins "no HTTP request was made"."""
    from src.framework.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    clinician, _ = await _seed_clinician(
        db_test_session_manager,
        npi="0000000000",
        first_name="Magic",
        last_name="Persona",
    )

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "magic NPI must short-circuit before NPPES is called; "
            f"got {request.method} {request.url}"
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(fail_handler))

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "verified"
    assert "dev_magic_npi" in verification.flags
    assert verification.nppes_result == {"dev_magic_npi": True}


async def test_run_does_not_short_circuit_on_magic_npi_outside_development(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    """The magic-NPI short-circuit is dev-only — even in
    `ENVIRONMENT=production` the orchestrator must fall through to
    NPPES. Pins the canary against the backdoor leaking into prod."""
    from src.framework.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    clinician, _ = await _seed_clinician(
        db_test_session_manager,
        npi="0000000000",
        first_name="Magic",
        last_name="Persona",
    )
    # NPPES says "not found" for this NPI in prod.
    http = _mock_http({"0000000000": {"results": []}})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
            )

    assert verification.status == "failed"
    assert "dev_magic_npi" not in verification.flags


async def test_run_with_commit_false_does_not_persist_until_caller_commits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`commit=False` lets the inline-create hook participate in the
    outer create transaction: the verification row is queued on the
    session, but a fresh connection won't see it until the caller
    commits."""
    clinician, _ = await _seed_clinician(db_test_session_manager, npi="1234567890")
    http = _mock_http({"1234567890": _nppes_basic_payload(first="X", last="Y")})

    async with db_test_session_manager() as session:
        async with http:
            verification = await run_clinician_verification(
                clinician_id=clinician.id,
                verification_repo=VerificationRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                http=http,
                actor_id=None,
                commit=False,
            )
        verification_id = verification.id
        # No `session.commit()` — the `async with` exit rolls back the
        # still-pending writes.

    async with db_test_session_manager() as fresh:
        assert await fresh.get(Verification, verification_id) is None


async def test_npi_failure_message_per_flag():
    """Each closed-vocabulary flag maps to a distinct user-facing message,
    and an unknown / empty flag set falls through to the generic line."""
    from types import SimpleNamespace

    from src.domain.logic.verifications.handlers import npi_failure_message

    def _v(*flags):
        return SimpleNamespace(flags=list(flags), status="failed")

    assert "OIG" in npi_failure_message(_v("oig_excluded:npi"))
    assert "NPPES registry" in npi_failure_message(_v("nppes_npi_not_found"))
    assert "first / last name" in npi_failure_message(_v("nppes_name_mismatch"))
    assert "organization name" in npi_failure_message(_v("nppes_org_name_mismatch"))
    assert "compare against" in npi_failure_message(_v("nppes_org_name_missing"))
    assert "required" in npi_failure_message(_v("nppes_skipped"))
    # Empty / unknown flags → the generic fallback.
    assert "couldn't verify" in npi_failure_message(_v())
    assert "couldn't verify" in npi_failure_message(_v("unknown_token"))
