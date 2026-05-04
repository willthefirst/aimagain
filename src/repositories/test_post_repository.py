"""Tests for `PostRepository`.

Exercises the parent + per-kind-detail invariants the repository owns:
create persists both rows in one flush, update writes per-kind fields to
the correct detail row, delete cascades the detail via the FK. Covered
for both `kind='note'` and `kind='client_referral'`.
"""

import uuid

import pytest
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import Uuid

from src.models import ClientReferralDetail, NoteDetail, Post
from src.repositories.post_repository import PostRepository
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


async def _seed_owner(db_test_session_manager):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
    return owner


# --- Note kind -----------------------------------------------------------


async def test_create_post_persists_parent_and_note_detail(
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


async def test_update_post_writes_to_note_detail(
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


async def test_delete_post_cascades_note_detail(
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


async def test_raw_sql_delete_post_cascades_via_fk(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A raw-SQL DELETE bypasses the ORM cascade — only the FK CASCADE can
    remove the detail row. Proves `PRAGMA foreign_keys = ON` is in effect."""
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
        await session.execute(
            text("DELETE FROM posts WHERE id = :pid").bindparams(
                bindparam("pid", type_=Uuid(as_uuid=True))
            ),
            {"pid": post_id},
        )
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
        assert detail_row is None


# --- Client referral kind ------------------------------------------------


async def test_create_post_persists_parent_and_client_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="client_referral", owner_id=owner.id)
        detail = ClientReferralDetail(description="needs placement")
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
                    select(ClientReferralDetail).filter(
                        ClientReferralDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "client_referral"
        assert detail_row is not None
        assert detail_row.description == "needs placement"


async def test_update_post_writes_to_client_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        created = await repo.create_post(
            Post(kind="client_referral", owner_id=owner.id),
            ClientReferralDetail(description="orig"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = await repo.get_post_by_id(post_id)
        await repo.update_post(post, description="new description")
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ClientReferralDetail).filter(
                        ClientReferralDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description == "new description"


async def test_delete_post_cascades_client_referral_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a client_referral parent removes its detail row via FK CASCADE."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        created = await repo.create_post(
            Post(kind="client_referral", owner_id=owner.id),
            ClientReferralDetail(description="doomed"),
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
                    select(ClientReferralDetail).filter(
                        ClientReferralDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert post_row is None
        assert detail_row is None


# --- Schema-level guard --------------------------------------------------


async def test_post_with_unknown_kind_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """The CHECK on `posts.kind` must reject any value outside the
    registered set. Guards against silently widening the kind universe
    by skipping a migration."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = PostRepository(session)
        post = Post(kind="not_a_kind", owner_id=owner.id)
        with pytest.raises(IntegrityError):
            await repo.create_post(post, NoteDetail(title="t", body="b"))
            await session.commit()
