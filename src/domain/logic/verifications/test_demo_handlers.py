"""Tests for the demo verification bypass pipelines.

`run_clinician_demo_verification` and `run_org_demo_verification` short-
circuit NPPES/OIG entirely and persist a Verification row with the
caller-chosen outcome. The test table pins each of the three outcome
branches for both entity types.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.organizations.repository import OrganizationRepository
from src.domain.logic.profile.handlers import _user_is_demo_context
from src.domain.logic.verifications import oig as oig_module
from src.domain.logic.verifications.handlers import (
    run_clinician_demo_verification,
    run_org_demo_verification,
)
from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Organization
from src.framework.audit.repository import AuditRepository
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
)

pytestmark = pytest.mark.asyncio

_LEIE_FIXTURE = Path(__file__).parent / "test_data" / "leie_sample.csv"


@pytest.fixture(autouse=True)
def _leie_path_env(monkeypatch):
    monkeypatch.setenv("LEIE_CSV_PATH", str(_LEIE_FIXTURE))
    oig_module._reset_cache_for_tests()
    yield
    oig_module._reset_cache_for_tests()


# --- Clinician demo bypass -----------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected_npi_match",
    [
        ("verified", "matched"),
        ("needs_review", "mismatch"),
        ("failed", "mismatch"),
    ],
)
async def test_clinician_demo_verification_outcome(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    outcome: str,
    expected_npi_match: str,
):
    """Each demo_outcome maps to the correct npi_match_status without
    touching NPPES or OIG."""
    owner = create_test_user(username=f"demo-{uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clinician = make_clinician_with_org(
                owner_id=owner.id,
                npi="9990000001",
                first_name="Demo",
                last_name="User",
            )
            session.add(clinician)

    async with db_test_session_manager() as session:
        verification = await run_clinician_demo_verification(
            clinician_id=clinician.id,
            demo_outcome=outcome,  # type: ignore[arg-type]
            verification_repo=VerificationRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            actor_id=owner.id,
        )

    assert verification.status == outcome
    assert "demo_bypass" in verification.flags

    async with db_test_session_manager() as session:
        refreshed = await ClinicianRepository(session).get_by_model_id(
            type(clinician), clinician.id
        )
        assert refreshed is not None
        assert refreshed.npi_match_status == expected_npi_match


async def test_clinician_demo_verified_sets_npi_verified_at(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `verified` demo outcome stamps `npi_verified_at`."""
    owner = create_test_user(username=f"demo-ts-{uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            clinician = make_clinician_with_org(
                owner_id=owner.id,
                npi="9990000002",
                clinician_verified=False,
                npi_match_status="none",
            )
            session.add(clinician)

    async with db_test_session_manager() as session:
        await run_clinician_demo_verification(
            clinician_id=clinician.id,
            demo_outcome="verified",
            verification_repo=VerificationRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            actor_id=owner.id,
        )

    async with db_test_session_manager() as session:
        refreshed = await ClinicianRepository(session).get_by_model_id(
            type(clinician), clinician.id
        )
        assert refreshed is not None
        assert refreshed.npi_verified_at is not None


# --- Organization demo bypass --------------------------------------------


@pytest.mark.parametrize(
    "outcome, expected_npi_match",
    [
        ("verified", "matched"),
        ("needs_review", "mismatch"),
        ("failed", "mismatch"),
    ],
)
async def test_org_demo_verification_outcome(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    outcome: str,
    expected_npi_match: str,
):
    """Each demo_outcome on an org maps to the correct npi_match_status."""
    owner = create_test_user(username=f"org-demo-{uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            org = make_organization_row(owner_id=owner.id, name="Demo Clinic")
            org.is_demo = True
            org.npi = "9990000003"
            session.add(org)

    async with db_test_session_manager() as session:
        verification = await run_org_demo_verification(
            org_id=org.id,
            demo_outcome=outcome,  # type: ignore[arg-type]
            verification_repo=VerificationRepository(session),
            org_repo=OrganizationRepository(session),
            audit_repo=AuditRepository(session),
            actor_id=owner.id,
        )

    assert verification.status == outcome
    assert "demo_bypass" in verification.flags

    async with db_test_session_manager() as session:
        refreshed = await session.get(Organization, org.id)
        assert refreshed is not None
        assert refreshed.npi_match_status == expected_npi_match


# --- _user_is_demo_context -----------------------------------------------


class _FakeOrg:
    def __init__(self, is_demo: bool):
        self.is_demo = is_demo


class _FakeRep:
    def __init__(self, is_demo: bool):
        self.org = _FakeOrg(is_demo)


class _FakeUser:
    def __init__(self, orgs=None, reps=None):
        self.organizations = orgs or []
        self.org_representations = reps or []


async def test_demo_context_true_when_owned_org_is_demo():
    user = _FakeUser(orgs=[_FakeOrg(is_demo=True)])
    assert _user_is_demo_context(user) is True  # type: ignore[arg-type]


async def test_demo_context_false_when_no_demo_orgs():
    user = _FakeUser(orgs=[_FakeOrg(is_demo=False)])
    assert _user_is_demo_context(user) is False  # type: ignore[arg-type]


async def test_demo_context_false_with_empty_orgs():
    user = _FakeUser()
    assert _user_is_demo_context(user) is False  # type: ignore[arg-type]


async def test_demo_context_true_via_org_representation():
    """Demo context detected through org_representations even with no
    owned orgs."""
    user = _FakeUser(reps=[_FakeRep(is_demo=True)])
    assert _user_is_demo_context(user) is True  # type: ignore[arg-type]
