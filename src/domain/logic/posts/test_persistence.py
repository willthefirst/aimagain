"""Tests for `Post` persistence invariants.

Exercises the parent + per-kind-detail invariants the polymorphic-create
path owns: create persists both rows in one flush, update writes per-kind
fields to the correct detail row, delete cascades the detail via the FK.
Covered for `kind='client_referral'` and `kind='provider_availability'`.

Posts have no bespoke repo class — these tests drive `BaseRepository`
directly, which is what the framework injects for the post route.
"""

import uuid

import pytest
from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import Uuid

from src.domain.models import ClientReferralDetail, Post, ProviderAvailabilityDetail
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import (
    create_test_user,
    make_client_referral_detail,
    make_provider_availability_detail,
)

pytestmark = pytest.mark.asyncio


async def _seed_owner(db_test_session_manager):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
    return owner


async def _create_post(repo, post, detail):
    """Test helper: persist a Post + detail using the framework's
    `create_polymorphic` (which lifted post-repo's `_attach_detail`
    into BaseRepository in B2 / #328)."""
    from src.domain.models import POST_KIND_BY_DETAIL_MODEL

    kind_spec = POST_KIND_BY_DETAIL_MODEL[type(detail)]
    return await repo.create_polymorphic(
        post, detail, detail_relationship=kind_spec.detail_relationship
    )


# --- Raw-SQL CASCADE check ----------------------------------------------


async def test_raw_sql_delete_post_cascades_via_fk(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A raw-SQL DELETE bypasses the ORM cascade — only the FK CASCADE can
    remove the detail row. Proves `PRAGMA foreign_keys = ON` is in effect."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="client_referral", owner_id=owner.id),
            make_client_referral_detail(description="doomed"),
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
                    select(ClientReferralDetail).filter(
                        ClientReferralDetail.post_id == post_id
                    )
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
        repo = BaseRepository(session)
        post = Post(kind="client_referral", owner_id=owner.id)
        detail = make_client_referral_detail(description="needs placement")
        created = await _create_post(repo, post, detail)
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
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="client_referral", owner_id=owner.id),
            make_client_referral_detail(description="orig"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        # Detail fields live on the detail row; framework's handle_update
        # (B3) reads `kind_spec.detail_relationship` to pick the right
        # target. At the repo level we just patch the detail directly.
        await repo.patch(post.client_referral_detail, description="new description")
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
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="client_referral", owner_id=owner.id),
            make_client_referral_detail(description="doomed"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.delete(post)
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


# --- Provider availability kind ------------------------------------------


async def test_create_post_persists_parent_and_provider_availability_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="provider_availability", owner_id=owner.id)
        detail = make_provider_availability_detail(practice_name="Acme Health")
        created = await _create_post(repo, post, detail)
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
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert post_row is not None
        assert post_row.kind == "provider_availability"
        assert detail_row is not None
        assert detail_row.practice_name == "Acme Health"


async def test_create_post_round_trips_free_text_fields(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`description`, `referral_instructions`, `website` persist + read back."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        detail = make_provider_availability_detail(
            description="Lead pitch",
            referral_instructions="Email the coordinator",
            website="example.com",
        )
        created = await _create_post(
            repo,
            Post(kind="provider_availability", owner_id=owner.id),
            detail,
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description == "Lead pitch"
        assert detail_row.referral_instructions == "Email the coordinator"
        assert detail_row.website == "example.com"


async def test_create_post_free_text_fields_default_null(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Omitting the three new fields persists them as NULL — additive
    columns must not break a row that doesn't supply them."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="provider_availability", owner_id=owner.id),
            make_provider_availability_detail(practice_name="No-extras"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.description is None
        assert detail_row.referral_instructions is None
        assert detail_row.website is None


async def test_update_post_writes_to_provider_availability_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="provider_availability", owner_id=owner.id),
            make_provider_availability_detail(practice_name="Acme"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.patch(
            post.provider_availability_detail, practice_name="Acme Renamed"
        )
        await session.commit()

    async with db_test_session_manager() as session:
        detail_row = (
            (
                await session.execute(
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
                    )
                )
            )
            .scalars()
            .first()
        )
        assert detail_row.practice_name == "Acme Renamed"


async def test_delete_post_cascades_provider_availability_detail(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a provider_availability parent removes its detail row via
    FK CASCADE."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        created = await _create_post(
            repo,
            Post(kind="provider_availability", owner_id=owner.id),
            make_provider_availability_detail(practice_name="Doomed"),
        )
        await session.commit()
        post_id = created.id

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = await repo.get_by_model_id(Post, post_id)
        await repo.delete(post)
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
                    select(ProviderAvailabilityDetail).filter(
                        ProviderAvailabilityDetail.post_id == post_id
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
    by skipping a migration. The retired `note` kind is now in this
    rejected set."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="not_a_kind", owner_id=owner.id)
        with pytest.raises(IntegrityError):
            await _create_post(repo, post, make_client_referral_detail(description="d"))
            await session.commit()


async def test_retired_note_kind_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`note` was removed from the registered kind set; inserts must fail."""
    owner = await _seed_owner(db_test_session_manager)

    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        post = Post(kind="note", owner_id=owner.id)
        with pytest.raises(IntegrityError):
            await _create_post(repo, post, make_client_referral_detail(description="d"))
            await session.commit()
