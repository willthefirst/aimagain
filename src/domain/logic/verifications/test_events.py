"""Unit tests for `events.py`.

Covers the two pure-function recompute helpers and the append-only
event writer extracted from the pipeline module.  These tests do not
need HTTP mocks — the NPPES pipeline is not exercised here.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.verifications.events import (
    recompute_clinician_claim,
    recompute_org_claim,
    record_verification_event,
)
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
# scope — the recompute_* tests are sync and would warn under a blanket
# pytestmark.


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
    `can_access_network` retention rule reads."""
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
