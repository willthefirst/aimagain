"""Route-level CRUD + privacy coverage for `/users/{user_id}/saved_searches`.

Pins the owned-subentity wiring end-to-end: create appends through
`User.saved_searches`, the bespoke list gates self-or-admin, patch /
delete resolve through the framework's generic sub-resource handlers,
and a viewer cannot read or write another user's searches.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import SavedSearch, User


async def _seed_other_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    other_id = uuid.uuid4()
    async with db_test_session_manager() as session:
        session.add(
            User(
                id=other_id,
                username=f"other-{other_id}",
                email=f"{other_id}@example.com",
                hashed_password="not-a-password",
                is_active=True,
                is_verified=True,
            )
        )
        await session.commit()
    return other_id


async def _seed_search(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    name: str,
    filters: dict | None = None,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    async with db_test_session_manager() as session:
        session.add(
            SavedSearch(id=row_id, user_id=user_id, name=name, filters=filters or {})
        )
        await session.commit()
    return row_id


@pytest.mark.asyncio
async def test_create_appends_search_with_empty_filters(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    response = await authenticated_client.post(
        f"/users/{logged_in_user.id}/saved_searches",
        data={"name": "Openings"},
    )
    assert response.status_code in (200, 201), response.text
    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(SavedSearch).where(SavedSearch.user_id == logged_in_user.id)
                )
            )
            .scalars()
            .all()
        )
    assert [r.name for r in rows] == ["Openings"]
    assert rows[0].filters == {}


@pytest.mark.asyncio
async def test_list_shows_own_searches(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await _seed_search(
        db_test_session_manager,
        user_id=logged_in_user.id,
        name="My openings",
        filters={"kind": "clinician_opening"},
    )
    response = await authenticated_client.get(
        f"/users/{logged_in_user.id}/saved_searches"
    )
    assert response.status_code == 200, response.text
    assert "My openings" in response.text


@pytest.mark.asyncio
async def test_patch_renames(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    row_id = await _seed_search(
        db_test_session_manager,
        user_id=logged_in_user.id,
        name="Old name",
        filters={"kind": "referral"},
    )
    response = await authenticated_client.patch(
        f"/users/{logged_in_user.id}/saved_searches/{row_id}",
        data={"name": "New name"},
    )
    assert response.status_code == 200, response.text
    async with db_test_session_manager() as session:
        row = await session.get(SavedSearch, row_id)
    assert row.name == "New name"
    # Filters left unchanged (not submitted on the form).
    assert row.filters == {"kind": "referral"}


@pytest.mark.asyncio
async def test_delete_removes(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    row_id = await _seed_search(
        db_test_session_manager, user_id=logged_in_user.id, name="Doomed"
    )
    response = await authenticated_client.delete(
        f"/users/{logged_in_user.id}/saved_searches/{row_id}"
    )
    assert response.status_code in (200, 204), response.text
    async with db_test_session_manager() as session:
        assert await session.get(SavedSearch, row_id) is None


@pytest.mark.asyncio
async def test_create_captures_json_filters_from_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """The posts-page "Save this search" form posts `name` + a hidden
    `filters` JSON string; the create handler parses + scopes it."""
    response = await authenticated_client.post(
        f"/users/{logged_in_user.id}/saved_searches",
        data={
            "name": "CA openings",
            "filters": '{"kind": "clinician_opening", "state": ["CA"], "bogus": 1}',
        },
    )
    assert response.status_code in (200, 201), response.text
    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(SavedSearch).where(SavedSearch.user_id == logged_in_user.id)
                )
            )
            .scalars()
            .one()
        )
    # JSON parsed; unknown key dropped.
    assert row.filters == {"kind": "clinician_opening", "state": ["CA"]}


@pytest.mark.asyncio
async def test_posts_page_shows_save_search_when_filtered(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    filtered = await authenticated_client.get("/posts?kind=clinician_opening")
    assert filtered.status_code == 200
    assert "Save this search" in filtered.text

    unfiltered = await authenticated_client.get("/posts")
    assert unfiltered.status_code == 200
    assert "Save this search" not in unfiltered.text


@pytest.mark.asyncio
async def test_list_card_links_to_rendered_posts_url(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A saved-search card's headline opens the rendered `/posts?…`
    URL — the "open" half of the round-trip."""
    await _seed_search(
        db_test_session_manager,
        user_id=logged_in_user.id,
        name="CA openings",
        filters={"kind": "clinician_opening", "state": ["CA"]},
    )
    response = await authenticated_client.get(
        f"/users/{logged_in_user.id}/saved_searches"
    )
    assert response.status_code == 200, response.text
    assert "/posts?kind=clinician_opening&amp;state=CA" in response.text


@pytest.mark.asyncio
async def test_list_forbidden_for_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other_id = await _seed_other_user(db_test_session_manager)
    await _seed_search(db_test_session_manager, user_id=other_id, name="Secret")
    response = await authenticated_client.get(f"/users/{other_id}/saved_searches")
    assert response.status_code == 403, response.text
    assert "Secret" not in response.text


@pytest.mark.asyncio
async def test_create_forbidden_under_other_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    other_id = await _seed_other_user(db_test_session_manager)
    response = await authenticated_client.post(
        f"/users/{other_id}/saved_searches",
        data={"name": "Intrusion"},
    )
    assert response.status_code == 403, response.text
    async with db_test_session_manager() as session:
        rows = (
            (
                await session.execute(
                    select(SavedSearch).where(SavedSearch.user_id == other_id)
                )
            )
            .scalars()
            .all()
        )
    assert rows == []
