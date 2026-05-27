"""Tests for the favorites orchestration handlers.

Pins three load-bearing invariants:

- **Idempotency without audit churn.** Re-favoriting and re-unfavoriting
  must NOT write a second audit row. Mutation handlers that write audit
  on every call would let a noisy client flood the audit log; the
  contract is "one row per actual state change."
- **Self-scoping.** The actor's id sources both the edge's `user_id` and
  the audit row's `actor_id` — a handler that read the user from a
  payload would be a CSRF surface.
- **Audit timing.** `before` is `None` on add; `after` is `None` on
  remove. Persisted forever; pin the shape.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from src.domain.logic.clinicians.repository import ClinicianRepository
from src.domain.logic.favorites.handlers import (
    handle_add_favorite,
    handle_list_my_favorites,
    handle_remove_favorite,
)
from src.domain.logic.favorites.repository import UserFavoriteRepository
from src.domain.models import User, UserFavorite
from src.framework.audit.core import AuditAction
from src.framework.audit.log import AuditLog
from src.framework.audit.repository import AuditRepository
from src.framework.http.exceptions import NotFoundError
from tests.helpers import create_test_user, make_clinician_with_org

pytestmark = pytest.mark.asyncio


def _fake_request(query_string: bytes = b"") -> Request:
    """Minimal Starlette Request used as a placeholder. `query_string`
    is consumed by `parse_page` / `base_query` when the handler
    paginates; callers that don't care leave the default empty."""
    return Request(
        {
            "type": "http",
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": query_string,
        }
    )


async def _seed_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> User:
    user = create_test_user(username=f"u-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    practice_name: str = "Acme Health",
):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    provider = make_clinician_with_org(owner_id=owner.id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(provider)
    return provider


async def test_add_favorite_creates_edge_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        edge = await handle_add_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )
        edge_id = edge.id

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_type == "user_favorite",
                        AuditLog.resource_id == edge_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].action == AuditAction.ADD_FAVORITE
        assert rows[0].actor_id == user.id
        assert rows[0].before is None
        assert rows[0].after is not None


async def test_add_favorite_is_idempotent_no_extra_audit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Re-favoriting returns the existing edge unchanged and does not
    write a second audit row."""
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        first = await handle_add_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )
        first_id = first.id

    async with db_test_session_manager() as session:
        second = await handle_add_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )
        assert second.id == first_id

    async with db_test_session_manager() as session:
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_type == "user_favorite",
                        AuditLog.resource_id == first_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_rows) == 1
        edge_rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(edge_rows) == 1


async def test_add_favorite_provider_not_found(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    async with db_test_session_manager() as session:
        with pytest.raises(NotFoundError):
            await handle_add_favorite(
                clinician_id=uuid.uuid4(),
                repo=UserFavoriteRepository(session),
                clinician_repo=ClinicianRepository(session),
                audit_repo=AuditRepository(session),
                requesting_user=user,
            )


async def test_remove_favorite_deletes_edge_and_audits(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        edge = await handle_add_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )
        edge_id = edge.id

    async with db_test_session_manager() as session:
        await handle_remove_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )

    async with db_test_session_manager() as session:
        edge_rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.id == edge_id)
                )
            )
            .scalars()
            .all()
        )
        assert edge_rows == []
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_id == edge_id,
                        AuditLog.action == AuditAction.REMOVE_FAVORITE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_rows) == 1
        assert audit_rows[0].before is not None
        assert audit_rows[0].after is None


async def test_remove_favorite_idempotent_no_audit_on_noop(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Unfavoriting when no edge exists is a no-op — no audit row."""
    user = await _seed_user(db_test_session_manager)
    provider = await _seed_provider(db_test_session_manager)

    async with db_test_session_manager() as session:
        await handle_remove_favorite(
            clinician_id=provider.id,
            repo=UserFavoriteRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=user,
        )

    async with db_test_session_manager() as session:
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.resource_type == "user_favorite",
                        AuditLog.action == AuditAction.REMOVE_FAVORITE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert audit_rows == []


async def test_list_my_favorites_returns_only_self_edges(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Self-scoping: another user's favorites are not visible."""
    me = await _seed_user(db_test_session_manager)
    other = await _seed_user(db_test_session_manager)
    mine = await _seed_provider(db_test_session_manager, practice_name="Mine")
    theirs = await _seed_provider(db_test_session_manager, practice_name="Theirs")

    async with db_test_session_manager() as session:
        await handle_add_favorite(
            clinician_id=mine.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=me,
        )
        await handle_add_favorite(
            clinician_id=theirs.id,
            repo=UserFavoriteRepository(session),
            clinician_repo=ClinicianRepository(session),
            audit_repo=AuditRepository(session),
            requesting_user=other,
        )

    async with db_test_session_manager() as session:
        context = await handle_list_my_favorites(
            request=_fake_request(),
            repo=UserFavoriteRepository(session),
            requesting_user=me,
        )

    names = [p.org.name for p in context["clinicians"]]
    assert names == ["Mine"]
    assert context["current_user"] == me
