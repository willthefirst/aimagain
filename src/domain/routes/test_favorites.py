"""Route-level tests for `/users/me/favorites/...`.

These exercise the add/remove toggle's wire shape: status codes for
create / re-create / delete / re-delete, and that the favorites list
page is gone (`GET /users/me/favorites` 404s — favorited clinicians are
browsed via `/clinicians?favorited=me`). Only the self-scoped path is
mounted; no parametric `/users/{user_id}/favorites/...` path exists.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import User, UserFavorite
from src.framework.audit.log import AuditLog
from tests.helpers import create_test_user, make_clinician_with_org

pytestmark = pytest.mark.asyncio


async def _seed_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    practice_name: str = "Acme Health",
) -> uuid.UUID:
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    clinician = make_clinician_with_org(owner_id=owner.id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(clinician)
        return clinician.id


async def test_add_favorite_returns_201_first_time(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    clinician_id = await _seed_clinician(db_test_session_manager)
    response = await authenticated_client.post(f"/users/me/favorites/{clinician_id}")
    assert response.status_code == 201
    assert response.headers["HX-Redirect"] == f"/clinicians/{clinician_id}"
    body = response.json()
    edge_id = uuid.UUID(body["id"])

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(UserFavorite).filter(UserFavorite.id == edge_id)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.user_id == logged_in_user.id
        assert row.clinician_id == clinician_id


async def test_add_favorite_idempotent_returns_200(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    clinician_id = await _seed_clinician(db_test_session_manager)
    first = await authenticated_client.post(f"/users/me/favorites/{clinician_id}")
    assert first.status_code == 201
    edge_id = uuid.UUID(first.json()["id"])

    second = await authenticated_client.post(f"/users/me/favorites/{clinician_id}")
    assert second.status_code == 200
    assert second.headers.get("HX-Refresh") == "true"
    assert uuid.UUID(second.json()["id"]) == edge_id

    async with db_test_session_manager() as session:
        audit_rows = (
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
        assert len(audit_rows) == 1


async def test_add_favorite_clinician_not_found(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.post(f"/users/me/favorites/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_remove_favorite_returns_204(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    clinician_id = await _seed_clinician(db_test_session_manager)
    await authenticated_client.post(f"/users/me/favorites/{clinician_id}")

    response = await authenticated_client.delete(f"/users/me/favorites/{clinician_id}")
    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == f"/clinicians/{clinician_id}"

    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(UserFavorite).filter(
                        UserFavorite.user_id == logged_in_user.id,
                        UserFavorite.clinician_id == clinician_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []


async def test_remove_favorite_idempotent_when_not_favorited(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Unfavoriting a clinician the user never favorited returns 204
    and writes no audit row."""
    clinician_id = await _seed_clinician(db_test_session_manager)
    response = await authenticated_client.delete(f"/users/me/favorites/{clinician_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        audit_rows = (
            (
                await session.execute(
                    select(AuditLog).filter(
                        AuditLog.actor_id == logged_in_user.id,
                        AuditLog.action == "remove_favorite",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert audit_rows == []


async def test_get_my_favorites_list_returns_404(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The favorites list page was removed — favorited clinicians are
    browsed via `/clinicians?favorited=me`. Only the add/remove toggle
    is mounted, so `GET /users/me/favorites` has no route and 404s."""
    response = await authenticated_client.get("/users/me/favorites")
    assert response.status_code == 404


async def test_add_favorite_requires_auth(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician_id = await _seed_clinician(db_test_session_manager)
    response = await test_client.post(f"/users/me/favorites/{clinician_id}")
    assert response.status_code in (302, 401)
