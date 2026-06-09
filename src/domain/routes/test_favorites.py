"""Route-level tests for `/users/me/favorites/...`.

These exercise the wire shape: status codes for create/re-create/delete/
re-delete, the rendered favorites page for self vs. anon, and that no
parametric `/users/{user_id}/favorites/...` path exists (the route file
intentionally mounts only the self-scoped path).
"""

import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
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


async def test_list_my_favorites_renders_html(
    superuser_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Uses `superuser_client` so the viewer clears `can_access_network`
    via the superuser bypass and the favorited clinician's practice name
    renders un-redacted. The redaction branch (where a non-network
    viewer sees their favorite's identifying fields as locked
    placeholders) is exercised separately by the clinician-card
    template tests."""
    first_id = await _seed_clinician(
        db_test_session_manager, practice_name="First Favorite"
    )
    await superuser_client.post(f"/users/me/favorites/{first_id}")

    response = await superuser_client.get("/users/me/favorites")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    parser = HTMLParser(response.text)
    body = parser.body.text() if parser.body else ""
    assert "First Favorite" in body


async def test_list_my_favorites_empty_state(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    response = await authenticated_client.get("/users/me/favorites")
    assert response.status_code == 200
    assert "No favorites" in response.text


async def test_anonymous_get_my_favorites_redirects_to_login(
    test_client: AsyncClient,
):
    """No `/users/{user_id}/favorites/...` parametric path exists.
    `/users/me/favorites` requires auth; unauthenticated requests
    redirect to login per `unauthorized_exception_handler`."""
    response = await test_client.get(
        "/users/me/favorites", headers={"accept": "text/html"}
    )
    assert response.status_code in (302, 401)


async def test_add_favorite_requires_auth(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    clinician_id = await _seed_clinician(db_test_session_manager)
    response = await test_client.post(f"/users/me/favorites/{clinician_id}")
    assert response.status_code in (302, 401)


async def test_list_my_favorites_renders_breadcrumb(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me/favorites` now renders a breadcrumb back-affordance
    pointing at the current user's profile page — auto-injected by
    `mount_edge_routes` via `USER_ENTITY.display_label_fn`."""
    response = await authenticated_client.get("/users/me/favorites")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    back = tree.css_first('nav[aria-label="breadcrumb"] a.breadcrumb-back')
    assert back is not None, "favorites list must render a breadcrumb back-affordance"
    assert back.attributes.get("href") == "/users/me"
    label = back.css_first("span.breadcrumb-back-label")
    assert label is not None and label.text(strip=True) == logged_in_user.username


async def test_empty_favorites_browse_clinicians_link_is_plain_anchor(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Empty-state copy on `/users/me/favorites` reads "Browse clinicians
    to add some" and points at `/clinicians`. The clinician spec no
    longer carries a `read_policy` — `/clinicians` is reachable for
    every authenticated viewer (identifying rows redact per-row at
    render time), so the link is a plain `<a href="/clinicians">`
    regardless of the viewer's network-access state. `entity_link`'s
    locked-popover branch only fires when the target spec declares a
    `read_policy` with `lock_reason`; no live spec does today."""
    response = await authenticated_client.get("/users/me/favorites")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    empty = tree.css_first("#favorites-empty")
    assert empty is not None, "expected empty-state to render for fresh user"
    plain = empty.css_first("a:not(.locked-link)")
    assert plain is not None, "Browse clinicians must render as a plain <a>"
    assert plain.attributes.get("href") == "/clinicians"
    assert "Browse clinicians" in plain.text()
    assert empty.css_first("a.locked-link") is None
