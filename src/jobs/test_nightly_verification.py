"""Pins the nightly-verification loop contract.

Two invariants this file guards:

1. Every eligible clinician is handed to `run_clinician_verification` once
   with `actor_id=None` (the system-actor convention shared with the
   admin retrigger endpoint when no user is logged in).
2. One clinician's failure does NOT stop the rest of the batch — the
   orchestrator commits per-clinician, so we must keep iterating after an
   exception is logged.

The orchestrator itself is stubbed: `test_handlers.py` already pins
the per-clinician behaviour, and this test cares only about the loop.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.jobs import nightly_verification
from tests.helpers import create_test_user, make_provider_with_org

pytestmark = pytest.mark.asyncio


async def _seed_clinicians(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    count: int,
):
    seeded = []
    async with db_test_session_manager() as session:
        async with session.begin():
            for i in range(count):
                user = create_test_user(username=f"owner-{i}")
                session.add(user)
                await session.flush()
                clinician = make_provider_with_org(
                    owner_id=user.id, practice_name=f"Practice {i}"
                )
                session.add(clinician)
                seeded.append(clinician)
    return seeded


async def test_run_nightly_verification_calls_orchestrator_per_clinician(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    monkeypatch.setattr(
        nightly_verification, "async_session_maker", db_test_session_manager
    )
    clinicians = await _seed_clinicians(db_test_session_manager, count=3)

    calls: list[dict] = []

    async def stub(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(nightly_verification, "run_clinician_verification", stub)

    await nightly_verification.run_nightly_verification()

    assert {c["clinician_id"] for c in calls} == {c.id for c in clinicians}
    assert all(c["actor_id"] is None for c in calls)


async def test_run_nightly_verification_continues_after_per_clinician_failure(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    monkeypatch.setattr(
        nightly_verification, "async_session_maker", db_test_session_manager
    )
    clinicians = await _seed_clinicians(db_test_session_manager, count=3)
    failing_id = clinicians[1].id

    seen: list = []

    async def stub(**kwargs):
        seen.append(kwargs["clinician_id"])
        if kwargs["clinician_id"] == failing_id:
            raise RuntimeError("simulated NPPES outage")

    monkeypatch.setattr(nightly_verification, "run_clinician_verification", stub)

    # The loop must swallow the per-clinician exception and keep going.
    await nightly_verification.run_nightly_verification()

    assert set(seen) == {c.id for c in clinicians}
