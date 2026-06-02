"""Tests for PostRepository owner-scoped read projections.

`list_clinician_openings`, `list_clinician_referrals`, and
`list_org_intakes` each project `/posts` down to the rows a single
owner is responsible for, via an inner join to the per-kind detail
table. The join inherently restricts to the matching kind (a Post has
a row in exactly one detail table), so these tests pin that:
  - only the owner's rows come back (owner-scoping), and
  - the kind is implied by the join (no cross-kind bleed).
"""

from __future__ import annotations

import uuid

import pytest

from src.domain.logic.posts.repository import PostRepository
from src.domain.models import Post
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import (
    create_test_user,
    make_clinician_with_org,
    make_intake_detail,
    make_opening_detail,
    make_organization_row,
    make_program,
    make_referral_detail,
)

pytestmark = pytest.mark.asyncio


async def _seed_user(db_test_session_manager):
    user = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _add_post(session, owner_id, detail, detail_relationship: str) -> Post:
    kind_map = {
        "referral_detail": "referral",
        "opening_detail": "clinician_opening",
        "intake_detail": "program_intake",
    }
    post = Post(kind=kind_map[detail_relationship], owner_id=owner_id)
    repo = BaseRepository(session)
    return await repo.create_polymorphic(
        post, detail, detail_relationship=detail_relationship
    )


async def test_list_clinician_openings_scopes_to_clinician(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            mine = make_clinician_with_org(owner_id=owner.id, practice_name="Mine")
            other = make_clinician_with_org(owner_id=owner.id, practice_name="Other")
            session.add(mine)
            session.add(other)

    async with db_test_session_manager() as session:
        async with session.begin():
            await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=mine.id),
                "opening_detail",
            )
            await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=other.id),
                "opening_detail",
            )
            # A referral on `mine` must NOT surface under openings.
            await _add_post(
                session,
                owner.id,
                make_referral_detail(referring_clinician_id=mine.id),
                "referral_detail",
            )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        rows = list(await repo.list_clinician_openings(mine.id))

    assert len(rows) == 1
    assert all(p.kind == "clinician_opening" for p in rows)


async def test_list_clinician_referrals_scopes_to_referring_clinician(
    db_test_session_manager,
):
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            mine = make_clinician_with_org(owner_id=owner.id, practice_name="Mine")
            other = make_clinician_with_org(owner_id=owner.id, practice_name="Other")
            session.add(mine)
            session.add(other)

    async with db_test_session_manager() as session:
        async with session.begin():
            await _add_post(
                session,
                owner.id,
                make_referral_detail(referring_clinician_id=mine.id),
                "referral_detail",
            )
            await _add_post(
                session,
                owner.id,
                make_referral_detail(referring_clinician_id=other.id),
                "referral_detail",
            )
            await _add_post(
                session,
                owner.id,
                make_opening_detail(clinician_id=mine.id),
                "opening_detail",
            )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        rows = list(await repo.list_clinician_referrals(mine.id))

    assert len(rows) == 1
    assert all(p.kind == "referral" for p in rows)


async def test_list_org_intakes_scopes_to_org_via_program(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            mine = make_organization_row(owner_id=owner.id, name="Mine Org")
            other = make_organization_row(owner_id=owner.id, name="Other Org")
            session.add(mine)
            session.add(other)
            mine_program = make_program(owner_id=owner.id, org_id=mine.id)
            other_program = make_program(owner_id=owner.id, org_id=other.id)
            session.add(mine_program)
            session.add(other_program)
        async with session.begin():
            await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=mine_program.id),
                "intake_detail",
            )
            await _add_post(
                session,
                owner.id,
                make_intake_detail(program_id=other_program.id),
                "intake_detail",
            )

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        rows = list(await repo.list_org_intakes(mine.id))

    assert len(rows) == 1
    assert all(p.kind == "program_intake" for p in rows)


async def test_list_clinician_openings_empty(db_test_session_manager):
    owner = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        async with session.begin():
            clinician = make_clinician_with_org(owner_id=owner.id)
            session.add(clinician)
        await session.refresh(clinician)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        rows = list(await repo.list_clinician_openings(clinician.id))

    assert rows == []
