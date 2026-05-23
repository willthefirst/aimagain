"""Tests for `VerificationRepository`.

Covers the three reader/writer methods used by the orchestrator (A4)
and the admin UI: `record(...)`, `latest_for_provider(...)`, and
`list_for_provider(...)`. The orchestrator's audit-write composition is
tested in A4; here we only exercise the persistence shape and the
ordering / pagination contract.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.verifications.repository import VerificationRepository
from src.domain.models import Provider, Verification
from tests.helpers import create_test_user, make_provider_with_org

pytestmark = pytest.mark.asyncio


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> Provider:
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            provider = make_provider_with_org(owner_id=user.id)
            session.add(provider)
    return provider


async def test_record_persists_a_new_row(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    provider = await _seed_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            repo = VerificationRepository(session)
            row = await repo.record(
                provider_id=provider.id,
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


async def test_latest_for_provider_returns_most_recent(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`latest_for_provider` orders by `created_at` desc and returns
    the top row. SQLite's server-default `CURRENT_TIMESTAMP` is
    second-precision, so two inserts in the same second tie on
    ordering. Pass `created_at` explicitly on the model constructor
    to force a deterministic ordering without burning real wall-clock
    on `asyncio.sleep(1.0+)`."""
    provider = await _seed_provider(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    provider_id=provider.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    provider_id=provider.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        latest = await repo.latest_for_provider(provider.id)
        assert latest is not None
        assert latest.status == "verified"


async def test_latest_for_provider_returns_none_when_no_history(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    provider = await _seed_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        assert await repo.latest_for_provider(provider.id) is None


async def test_list_for_provider_orders_newest_first(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Same SQLite-tie problem as `test_latest_for_provider_returns_most_recent`
    — pass `created_at` explicitly to avoid a second-precision tie."""
    provider = await _seed_provider(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    provider_id=provider.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    provider_id=provider.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        rows = await repo.list_for_provider(provider.id)
        assert [r.status for r in rows] == ["verified", "failed"]


async def test_list_for_provider_honors_limit_and_offset(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Two-row pagination sanity: offset=1 limit=1 returns the second
    row from the newest-first listing."""
    provider = await _seed_provider(db_test_session_manager)
    earlier = datetime.now(timezone.utc)
    later = earlier + timedelta(seconds=1)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    provider_id=provider.id, status="failed", created_at=earlier
                )
            )
            session.add(
                Verification(
                    provider_id=provider.id, status="verified", created_at=later
                )
            )

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        page = await repo.list_for_provider(provider.id, limit=1, offset=1)
        # newest first: [verified, failed] → offset=1 limit=1 → [failed]
        assert [r.status for r in page] == ["failed"]


async def test_list_for_provider_filters_out_other_providers(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A `Verification` is per-provider; sibling rows on a different
    provider must not bleed into the list."""
    provider_a = await _seed_provider(db_test_session_manager)
    provider_b = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(provider_id=provider_a.id, status="verified"))
            session.add(Verification(provider_id=provider_b.id, status="failed"))

    async with db_test_session_manager() as session:
        repo = VerificationRepository(session)
        rows = await repo.list_for_provider(provider_a.id)
        assert [r.status for r in rows] == ["verified"]
