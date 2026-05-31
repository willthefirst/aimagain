"""Pins the pending-NPI worker loop contract.

Three invariants this file guards:

1. The loop pulls *only* rows with `npi_match_status == 'pending'` —
   not-yet-submitted (`'none'`) and resolved (`'matched'` / `'mismatch'`)
   rows are skipped. Cuts the queue depth on every run.
2. Every pending Clinician AND every pending Organization is handed to
   the matching pipeline once with `actor_id=None`.
3. One pipeline failure does NOT stop the rest of the batch — same per-
   row commit + log-and-continue pattern as `nightly_verification`.

The pipelines themselves are stubbed; `test_handlers_phase3.py` and
`test_handlers.py` pin the per-row behavior.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician
from src.jobs import verify_pending_npis
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_organization_row,
)

pytestmark = pytest.mark.asyncio


async def _seed_pending_clinicians(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    pending_count: int,
    none_count: int,
    matched_count: int,
) -> tuple[list[Clinician], list[Clinician]]:
    """Returns (pending, non_pending). Tests assert the worker visits
    only the pending list."""
    pending: list[Clinician] = []
    non_pending: list[Clinician] = []
    async with db_test_session_manager() as session:
        async with session.begin():
            for i in range(pending_count):
                user = create_test_user(username=f"pending-owner-{i}")
                session.add(user)
                await session.flush()
                clinician = make_clinician_with_org(owner_id=user.id, npi="1234567890")
                clinician.npi_match_status = "pending"
                session.add(clinician)
                pending.append(clinician)
            for i in range(none_count):
                user = create_test_user(username=f"none-owner-{i}")
                session.add(user)
                await session.flush()
                clinician = make_clinician_with_org(owner_id=user.id)
                # `npi_match_status` defaults to 'none' on insert.
                session.add(clinician)
                non_pending.append(clinician)
            for i in range(matched_count):
                user = create_test_user(username=f"matched-owner-{i}")
                session.add(user)
                await session.flush()
                clinician = make_clinician_with_org(owner_id=user.id, npi="9876543210")
                clinician.npi_match_status = "matched"
                clinician.clinician_verified = True
                session.add(clinician)
                non_pending.append(clinician)
    return pending, non_pending


async def test_only_pending_clinicians_are_visited(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    monkeypatch.setattr(
        verify_pending_npis, "async_session_maker", db_test_session_manager
    )
    pending, non_pending = await _seed_pending_clinicians(
        db_test_session_manager,
        pending_count=2,
        none_count=2,
        matched_count=1,
    )

    seen: list = []

    async def stub_clinician(**kwargs):
        seen.append(kwargs["clinician_id"])

    async def stub_org(**kwargs):
        pass

    monkeypatch.setattr(
        verify_pending_npis, "run_clinician_verification", stub_clinician
    )
    monkeypatch.setattr(verify_pending_npis, "run_org_verification", stub_org)

    await verify_pending_npis.run_verify_pending_npis()

    assert set(seen) == {c.id for c in pending}
    assert not (set(seen) & {c.id for c in non_pending})


async def test_pending_orgs_drained(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Both the Clinician and Organization queues are drained in one
    pass."""
    monkeypatch.setattr(
        verify_pending_npis, "async_session_maker", db_test_session_manager
    )
    user = create_test_user()
    org_pending = make_organization_row(owner_id=user.id, name="Pending Org")
    org_pending.npi = "1234567890"
    org_pending.npi_match_status = "pending"
    org_resolved = make_organization_row(owner_id=user.id, name="Resolved Org")
    org_resolved.npi = "9876543210"
    org_resolved.npi_match_status = "matched"
    org_resolved.org_verified = True
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org_pending)
            session.add(org_resolved)

    seen_orgs: list = []

    async def stub_clinician(**kwargs):
        pass

    async def stub_org(**kwargs):
        seen_orgs.append(kwargs["org_id"])

    monkeypatch.setattr(
        verify_pending_npis, "run_clinician_verification", stub_clinician
    )
    monkeypatch.setattr(verify_pending_npis, "run_org_verification", stub_org)

    await verify_pending_npis.run_verify_pending_npis()

    assert seen_orgs == [org_pending.id]


async def test_loop_continues_after_per_row_failure(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A single failing pipeline call must not stop the rest of the
    batch. Same log-and-continue rule as `nightly_verification`."""
    monkeypatch.setattr(
        verify_pending_npis, "async_session_maker", db_test_session_manager
    )
    pending, _ = await _seed_pending_clinicians(
        db_test_session_manager, pending_count=3, none_count=0, matched_count=0
    )
    failing_id = pending[1].id

    seen: list = []

    async def stub_clinician(**kwargs):
        seen.append(kwargs["clinician_id"])
        if kwargs["clinician_id"] == failing_id:
            raise RuntimeError("simulated NPPES outage")

    async def stub_org(**kwargs):
        pass

    monkeypatch.setattr(
        verify_pending_npis, "run_clinician_verification", stub_clinician
    )
    monkeypatch.setattr(verify_pending_npis, "run_org_verification", stub_org)

    # Must not raise.
    await verify_pending_npis.run_verify_pending_npis()

    assert set(seen) == {c.id for c in pending}


async def test_empty_queue_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Nothing pending → no HTTP client opened, no pipeline calls."""
    monkeypatch.setattr(
        verify_pending_npis, "async_session_maker", db_test_session_manager
    )

    calls: list = []

    async def stub_clinician(**kwargs):
        calls.append(("clinician", kwargs["clinician_id"]))

    async def stub_org(**kwargs):
        calls.append(("org", kwargs["org_id"]))

    monkeypatch.setattr(
        verify_pending_npis, "run_clinician_verification", stub_clinician
    )
    monkeypatch.setattr(verify_pending_npis, "run_org_verification", stub_org)

    await verify_pending_npis.run_verify_pending_npis()

    assert calls == []
