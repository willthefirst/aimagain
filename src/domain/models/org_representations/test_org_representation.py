"""Direct DB-layer tests for `OrgRepresentation`.

Exercises the invariants the model + migration own — the three role /
method / status CHECKs against their `LabeledChoice` vocabularies, the
unique `(user_id, org_id)` pair, FK cascades on user/org delete, and
the `approved_by` `SET NULL` rule.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Organization, OrgRepresentation, User
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


def _make_rep(user: User, org: Organization, **overrides) -> OrgRepresentation:
    defaults = dict(
        user_id=user.id,
        org_id=org.id,
        role="coordinator",
        authority_method="admin_review",
    )
    return OrgRepresentation(**{**defaults, **overrides})


async def _seed_user_and_org(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> tuple[User, Organization]:
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(org)
    return user, org


async def test_create_org_representation_defaults_to_pending(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A row created with just `role` + `authority_method` lands at
    `authority_status='pending'` via server-default; `archived_at` and
    `approved_by` start null."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    rep = _make_rep(user, org)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(rep)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(OrgRepresentation).filter(OrgRepresentation.id == rep.id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded.authority_status == "pending"
        assert loaded.archived_at is None
        assert loaded.approved_by is None


async def test_role_check_rejects_unknown_value(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_rep(user, org, role="not_a_role"))


async def test_authority_method_check_rejects_unknown_value(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_rep(user, org, authority_method="not_a_method"))


async def test_authority_status_check_rejects_unknown_value(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_rep(user, org, authority_status="not_a_status"))


async def test_uniqueness_on_user_org_pair(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`uq_org_representations_user_org` keeps a user from holding two
    representations on the same org. Reclaim-after-archive currently
    requires the application layer to un-archive instead of creating
    a fresh row (see the README)."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_make_rep(user, org))

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_rep(user, org))


async def test_cascade_on_user_delete_removes_rep(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    rep_id = uuid.uuid4()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_make_rep(user, org, id=rep_id))

    async with db_test_session_manager() as session:
        async with session.begin():
            persisted = await session.get(User, user.id)
            await session.delete(persisted)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(OrgRepresentation).filter(OrgRepresentation.id == rep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is None


async def test_cascade_on_org_delete_removes_rep(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user, org = await _seed_user_and_org(db_test_session_manager)
    rep_id = uuid.uuid4()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_make_rep(user, org, id=rep_id))

    async with db_test_session_manager() as session:
        async with session.begin():
            persisted = await session.get(Organization, org.id)
            await session.delete(persisted)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(OrgRepresentation).filter(OrgRepresentation.id == rep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is None


async def test_approved_by_set_null_on_approver_delete(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting the user who approved a representation should clear
    `approved_by` (not cascade-delete the rep — that user's departure
    doesn't invalidate the authority they conferred)."""
    user, org = await _seed_user_and_org(db_test_session_manager)
    approver = create_test_user(username="approver")
    rep_id = uuid.uuid4()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(approver)
            session.add(_make_rep(user, org, id=rep_id, approved_by=approver.id))

    async with db_test_session_manager() as session:
        async with session.begin():
            persisted = await session.get(User, approver.id)
            await session.delete(persisted)

    async with db_test_session_manager() as session:
        loaded = (
            (
                await session.execute(
                    select(OrgRepresentation).filter(OrgRepresentation.id == rep_id)
                )
            )
            .scalars()
            .first()
        )
        assert loaded is not None
        assert loaded.approved_by is None
