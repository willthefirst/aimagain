"""Tests for the `Verification` model.

Exercises the DB-layer invariants: the named `status` CHECK constraint
rejects bogus values, defaults for `flags` / `oig_match` apply when the
columns are omitted, and provider cascade removes verification history
when its parent provider is deleted (so orphan rows can't pile up).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


@pytest.mark.parametrize("status", ["verified", "needs_review", "failed"])
async def test_verification_accepts_valid_status(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    status: str,
):
    provider = await _seed_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    provider_id=provider.id,
                    status=status,
                    oig_match=False,
                )
            )

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(Verification.provider_id == provider.id)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.status == status


async def test_verification_rejects_unknown_status(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`ck_verifications_status` rejects anything outside
    `VERIFICATION_STATUSES`."""
    provider = await _seed_provider(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    Verification(
                        provider_id=provider.id,
                        status="not_a_real_status",
                        oig_match=False,
                    )
                )


async def test_verification_defaults_flags_and_oig_match(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting `flags` and `oig_match` falls back to the server
    defaults — empty list and `False`."""
    provider = await _seed_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(provider_id=provider.id, status="verified"))

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(Verification.provider_id == provider.id)
                )
            )
            .scalars()
            .first()
        )
        assert row.flags == []
        assert row.oig_match is False
        assert row.nppes_result is None
        assert row.name_match_score is None


async def test_verification_cascades_on_provider_delete(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a `Provider` removes its verification history via the
    `provider_id` FK `ON DELETE CASCADE` — orphan rows can't survive."""
    provider = await _seed_provider(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(provider_id=provider.id, status="verified"))
            session.add(Verification(provider_id=provider.id, status="needs_review"))

    provider_id = provider.id
    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Provider, provider_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(Verification).filter(Verification.provider_id == provider_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
