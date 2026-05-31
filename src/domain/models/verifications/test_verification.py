"""Tests for the `Verification` model.

Exercises the DB-layer invariants: the named `status` CHECK constraint
rejects bogus values, defaults for `flags` / `oig_match` apply when the
columns are omitted, and clinician cascade removes verification history
when its parent clinician is deleted (so orphan rows can't pile up).

After the polymorphic refactor (Phase 1b), the table also enforces a
`subject_type` discriminator (`'clinician'` | `'organization'`) plus a
shape CHECK pinning exactly one of (`clinician_id`, `org_id`) per
discriminator value. These are exercised in the dedicated "polymorphic"
section near the bottom of the file.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, Organization, Verification
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


async def _seed_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> Clinician:
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    clinician = Clinician(
        owner_id=user.id,
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="no",
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
    )
    clinician.org = org
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(clinician)
    return clinician


@pytest.mark.parametrize("status", ["verified", "needs_review", "failed"])
async def test_verification_accepts_valid_status(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    status: str,
):
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    clinician_id=clinician.id,
                    status=status,
                    oig_match=False,
                )
            )

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician.id
                    )
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
    clinician = await _seed_clinician(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    Verification(
                        clinician_id=clinician.id,
                        status="not_a_real_status",
                        oig_match=False,
                    )
                )


async def test_verification_defaults_flags_and_oig_match(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting `flags` and `oig_match` falls back to the server
    defaults — empty list and `False`."""
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(clinician_id=clinician.id, status="verified"))

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician.id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert row.flags == []
        assert row.oig_match is False
        assert row.nppes_result is None
        assert row.name_match_score is None


async def test_verification_cascades_on_clinician_delete(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a `Clinician` removes its verification history via the
    `clinician_id` FK `ON DELETE CASCADE` — orphan rows can't survive."""
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(clinician_id=clinician.id, status="verified"))
            session.add(Verification(clinician_id=clinician.id, status="needs_review"))

    clinician_id = clinician.id
    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Clinician, clinician_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


# --- polymorphic subject (Phase 1b) --------------------------------------


async def test_verification_defaults_to_clinician_subject(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A row inserted with only `clinician_id` + `status` falls into the
    `'clinician'` discriminator path via server-default."""
    clinician = await _seed_clinician(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(Verification(clinician_id=clinician.id, status="verified"))

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(
                        Verification.clinician_id == clinician.id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert row.subject_type == "clinician"
        assert row.event_type == "npi_resolved"
        assert row.org_id is None


async def test_verification_accepts_org_subject(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An org-scoped verification row carries `org_id` and discards
    `clinician_id` — the shape CHECK enforces the invariant."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                Verification(
                    subject_type="organization",
                    org_id=org.id,
                    event_type="npi_resolved",
                    status="verified",
                )
            )

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
        assert row.subject_type == "organization"
        assert row.clinician_id is None
        assert row.org_id == org.id


async def test_verification_shape_check_rejects_both_subjects(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`ck_verifications_subject_shape` refuses rows that set both
    `clinician_id` AND `org_id` — exactly one must be present."""
    clinician = await _seed_clinician(db_test_session_manager)
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    Verification(
                        subject_type="clinician",
                        clinician_id=clinician.id,
                        org_id=org.id,
                        status="verified",
                    )
                )


async def test_verification_shape_check_rejects_neither_subject(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Rows with neither `clinician_id` nor `org_id` are also rejected."""
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    Verification(
                        subject_type="clinician",
                        status="verified",
                    )
                )


async def test_verification_rejects_unknown_event_type(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`ck_verifications_event_type` keeps `event_type` on the §9 closed
    vocab."""
    clinician = await _seed_clinician(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    Verification(
                        clinician_id=clinician.id,
                        status="verified",
                        event_type="not_a_real_event_type",
                    )
                )


async def test_verification_cascades_on_org_delete(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting an `Organization` removes its verification history via
    the `org_id` FK `ON DELETE CASCADE` — symmetric with the clinician
    cascade."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
            session.add(
                Verification(
                    subject_type="organization",
                    org_id=org.id,
                    status="verified",
                )
            )
    org_id = org.id

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Organization, org_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(Verification).filter(Verification.org_id == org_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
