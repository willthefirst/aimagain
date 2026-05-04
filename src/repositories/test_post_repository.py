"""Tests for `PostRepository`.

Exercises the parent + per-kind-detail invariants the repository owns:
create persists both rows in one flush, update writes title/body to the
detail row (not the parent), delete cascades the detail via the FK.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import NoteDetail, Post
from src.repositories.post_repository import PostRepository
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


async def _seed_owner(db_test_session_manager):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
    return owner


async def test_create_post_persists_parent_and_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="note", owner_id=owner.id)
        detail = NoteDetail(title="t", body="b")
        created = await repo.create_post(post, detail)
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(NoteDetail).filter(NoteDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "note"
        assert detail_row is not None
        assert detail_row.title == "t"
        assert detail_row.body == "b"


async def test_update_post_writes_to_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        created = await repo.create_post(
            Post(kind="note", owner_id=owner.id),
            NoteDetail(title="orig", body="orig body"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = await repo.get_post_by_id(post_id)
        await repo.update_post(post, title="new title")
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(NoteDetail).filter(NoteDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.title == "new title"
        assert detail_row.body == "orig body"


async def test_delete_post_cascades_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting the parent must remove the detail row via the FK CASCADE."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        created = await repo.create_post(
            Post(kind="note", owner_id=owner.id),
            NoteDetail(title="t", body="b"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = await repo.get_post_by_id(post_id)
        await repo.delete_post(post)
        await session.commit()

    async with db_test_session_manager() as session:
        post_row = (
            (await session.execute(select(Post).filter(Post.id == post_id)))
            .scalars()
            .first()
        )
        detail_row = (
            (
                await session.execute(
                    select(NoteDetail).filter(NoteDetail.post_id == post_id)
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None
