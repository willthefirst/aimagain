"""Tests for `VerificationRepository`.

Covers the three reader/writer methods used by the orchestrator (A4)
and the admin UI: `record(...)`, `latest_for_clinician(...)`, and
`list_for_clinician(...)`. The orchestrator's audit-write composition is
tested in A4; here we only exercise the persistence shape and the
ordering / pagination contract.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Clinician, Verification
from tests.helpers import create_test_user, make_clinician_with_org

pytestmark = pytest.mark.asyncio


async def _seed_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> Clinician:
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            clinician = make_clinician_with_org(owner_id=user.id)
            session.add(clinician)
    return clinician


async def test_record_persists_a_new_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            repo = VerificationRepository(session)
            row = await repo.record(
                clinician_id=clinician.id,
                status="verified",
                flags=["nppes_npi_not_found"],
                nppes_result={"results": []},
                oig_match=False,
                name_match_score=0.87,
            )
            assert row.id is not None
            assert row.status == "verified"
            assert row.flags == ["nppes_npi_not_found"]
            assert row.nppes_result == {"results": []}
            assert row.name_match_score == pytest.approx(0.87)


async def test_latest_for_clinician_returns_most_recent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`latest_for_clinician` orders by `created_at` desc and returns
    the top row. SQLite's server-default `CURRENT_TIMESTAMP` is
    second-precision, so two inserts in the same second tie on
    ordering. Pass `created_at` explicitly on the model constructor
    to force a deterministic ordering without burning real wall-clock
    on `asyncio.sleep(1.0+)`."""
    clinician = await _seed_clinician(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    clinician_id=clinician.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    clinician_id=clinician.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        latest = await repo.latest_for_clinician(clinician.id)
        assert latest is not None
        assert latest.status == "verified"


async def test_latest_for_clinician_returns_none_when_no_history(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        assert await repo.latest_for_clinician(clinician.id) is None


async def test_list_for_clinician_orders_newest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Same SQLite-tie problem as `test_latest_for_clinician_returns_most_recent`
    — pass `created_at` explicitly to avoid a second-precision tie."""
    clinician = await _seed_clinician(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    clinician_id=clinician.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    clinician_id=clinician.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        rows = await repo.list_for_clinician(clinician.id)
        assert [r.status for r in rows] == ["verified", "failed"]


async def test_list_for_clinician_honors_limit_and_offset(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Two-row pagination sanity: offset=1 limit=1 returns the second
    row from the newest-first listing."""
    clinician = await _seed_clinician(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    clinician_id=clinician.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    clinician_id=clinician.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        page = await repo.list_for_clinician(clinician.id, limit=1, offset=1)
        # newest first: [verified, failed] → offset=1 limit=1 → [failed]
        assert [r.status for r in page] == ["failed"]


async def test_list_for_clinician_filters_out_other_clinicians(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `Verification` is per-clinician; sibling rows on a different
    clinician must not bleed into the list."""
    clinician_a = await _seed_clinician(db_test_session_manager)
    clinician_b = await _seed_clinician(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(clinician_id=clinician_a.id, status="verified"))
            session.add(Verification(clinician_id=clinician_b.id, status="failed"))

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        rows = await repo.list_for_clinician(clinician_a.id)
        assert [r.status for r in rows] == ["verified"]
