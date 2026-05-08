import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy import select

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import AuditLog, User
from src.repositories.audit_repository import AuditRepository
from tests.helpers import create_test_user, make_provider_profile, promote_to_admin

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# --- Base template nav ---------------------------------------------------


async def test_base_template_renders_primary_nav(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Pages rendered from base.html include nav links to the main sections."""
    response = await authenticated_client.get("/users")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    nav_items = tree.css("#primary-nav > li > a")
    hrefs = {a.attributes.get("href") for a in nav_items}
    assert {"/posts", "/users", "/providers"} <= hrefs


# --- Listing -------------------------------------------------------------


async def test_list_users_empty(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Test GET /users returns HTML with no other users message when only logged in user exists."""
    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No users found" in tree.body.text()
    link_node = tree.css_first(f'a[href*="/users"]')
    assert link_node is not None, "Refresh link not found"


async def test_list_users_one_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /users returns HTML listing one other user."""
    test_username = f"test-user-{uuid.uuid4()}"
    other_user = create_test_user(username=test_username)

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_user)

    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul:not(#primary-nav) > li")
    assert len(user_list_items) == 1, "Expected one user in the list"
    assert (
        test_username in user_list_items[0].text()
    ), "Correct username not found in list item"
    assert (
        logged_in_user.username not in user_list_items[0].text()
    ), "Logged in user should not be listed"
    assert "No users found" not in tree.body.text()


async def test_list_users_multiple_users(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /users returns HTML listing multiple other users."""
    user1 = create_test_user(username=f"test-user-one-{uuid.uuid4()}")
    user2 = create_test_user(username=f"test-user-two-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user1, user2])

    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul:not(#primary-nav) > li")
    assert len(user_list_items) == 2, "Expected two users in the list"

    usernames_found = {item.text() for item in user_list_items}
    assert any(
        user1.username in u for u in usernames_found
    ), f"{user1.username} not found in list"
    assert any(
        user2.username in u for u in usernames_found
    ), f"{user2.username} not found in list"
    assert all(
        logged_in_user.username not in u for u in usernames_found
    ), "Logged in user should not be listed"
    assert "No users found" not in tree.body.text()


# --- Admin actions partial visibility ------------------------------------


async def test_list_hides_admin_actions_for_non_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin viewers must not see deactivate/delete buttons."""
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    assert (
        tree.css_first("span.admin-actions") is None
    ), "Non-admin should not see admin action buttons"


async def test_list_shows_admin_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewers see deactivate + delete buttons on each non-self row."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    actions = tree.css("span.admin-actions")
    assert len(actions) == 1, "Expected one admin-actions span (one non-self row)"
    buttons = actions[0].css("button")
    button_labels = {b.text().strip() for b in buttons}
    assert "Deactivate" in button_labels
    assert "Delete" in button_labels


async def test_list_shows_reactivate_for_deactivated_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A deactivated user shows 'Reactivate' rather than 'Deactivate'."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    other = create_test_user(username=f"target-{uuid.uuid4()}", is_active=False)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other)

    response = await authenticated_client.get("/users")
    tree = HTMLParser(response.text)
    button_labels = {b.text().strip() for b in tree.css("span.admin-actions button")}
    assert "Reactivate" in button_labels
    assert "Deactivate" not in button_labels


# --- Detail page ---------------------------------------------------------


async def test_get_user_detail_renders(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """GET /users/{id} renders the detail page for an existing user."""
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(username=target_username)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert target_username in tree.body.text()


async def test_get_user_detail_404(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """GET /users/{id} returns 404 for an unknown id."""
    response = await authenticated_client.get(f"/users/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_detail_shows_admin_actions_for_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin viewing another user's detail page sees the actions partial."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    assert tree.css_first("span.admin-actions") is not None


async def test_detail_hides_admin_actions_for_non_admin(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin viewing another user's detail page does not see actions."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    tree = HTMLParser(response.text)
    assert tree.css_first("span.admin-actions") is None


async def test_detail_shows_provider_profiles_empty_state(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """User with no provider profiles → empty-state copy on the detail page."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-detail-provider-profiles") is None
    empty = tree.css_first("#user-detail-provider-profiles-empty")
    assert empty is not None
    assert "No provider profiles yet" in empty.text()


async def test_detail_lists_owned_provider_profiles(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """User with multiple profiles → all are linked from the detail page."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    first = make_provider_profile(user_id=target.id, practice_name="First")
    second = make_provider_profile(user_id=target.id, practice_name="Second")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([first, second])
        await session.refresh(first)
        await session.refresh(second)

    response = await authenticated_client.get(f"/users/{target.id}")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-detail-provider-profiles-empty") is None
    items = tree.css("#user-detail-provider-profiles > li")
    assert len(items) == 2
    hrefs = {
        a.attributes.get("href") for a in tree.css("#user-detail-provider-profiles a")
    }
    assert hrefs == {f"/providers/{first.id}", f"/providers/{second.id}"}


# --- Activation endpoint -------------------------------------------------


async def test_admin_can_deactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert response.headers.get("HX-Refresh") == "true"

    # Confirm persisted
    async with db_test_session_manager() as session:
        result = await session.execute(select(User).filter(User.id == target.id))
        refreshed = result.scalars().first()
        assert refreshed.is_active is False


async def test_admin_can_reactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=False)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "active"},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


async def test_non_admin_cannot_deactivate_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Non-admin gets 403 even with a valid body — backend enforces authz, not just templates."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403


async def test_admin_cannot_deactivate_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Self-guard: admin acting on their own id is rejected at the logic layer."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.put(
        f"/users/{logged_in_user.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403


async def test_activation_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.put(
        f"/users/{uuid.uuid4()}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 404


# --- Delete endpoint -----------------------------------------------------


async def test_admin_can_delete_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.delete(f"/users/{target.id}")
    assert response.status_code == 204
    assert response.headers.get("HX-Redirect") == "/users"

    async with db_test_session_manager() as session:
        result = await session.execute(select(User).filter(User.id == target.id))
        assert result.scalars().first() is None


async def test_non_admin_cannot_delete_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.delete(f"/users/{target.id}")
    assert response.status_code == 403

    # Row still exists
    async with db_test_session_manager() as session:
        result = await session.execute(select(User).filter(User.id == target.id))
        assert result.scalars().first() is not None


async def test_admin_cannot_delete_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.delete(f"/users/{logged_in_user.id}")
    assert response.status_code == 403


async def test_delete_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    response = await authenticated_client.delete(f"/users/{uuid.uuid4()}")
    assert response.status_code == 404


# --- Audit log -----------------------------------------------------------


async def test_set_user_activation_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful PUT /users/{id}/activation writes one audit row
    capturing before/after activation state, with the admin as actor."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}", is_active=True)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.put(
        f"/users/{target.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 200

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(resource_type="user", resource_id=target.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "set_user_activation"
        assert row.before == {"is_active": True}
        assert row.after == {"is_active": False}


async def test_failed_activation_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A 403 (admin self-guard) leaves no audit trail."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.put(
        f"/users/{logged_in_user.id}/activation",
        json={"state": "deactivated"},
    )
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type="user", resource_id=logged_in_user.id
        )
        assert rows == []


async def test_delete_user_writes_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Each successful DELETE /users/{id} writes one audit row capturing
    the user's pre-delete state in `before`, with `after=None`."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target_username = f"target-{uuid.uuid4()}"
    target = create_test_user(
        username=target_username, is_active=True, is_superuser=False
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    target_id = target.id
    target_email = target.email

    response = await authenticated_client.delete(f"/users/{target_id}")
    assert response.status_code == 204

    async with db_test_session_manager() as session:
        # User row gone
        result = await session.execute(select(User).filter(User.id == target_id))
        assert result.scalars().first() is None

        # Audit row preserved with the admin as actor
        result = await session.execute(
            select(AuditLog).filter(
                AuditLog.resource_type == "user",
                AuditLog.resource_id == target_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.actor_id == logged_in_user.id
        assert row.action == "delete_user"
        assert row.before == {
            "username": target_username,
            "email": target_email,
            "is_active": True,
            "is_superuser": False,
        }
        assert row.after is None


async def test_failed_delete_writes_no_audit_row(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Self-delete attempts get 403; no audit row written."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.delete(f"/users/{logged_in_user.id}")
    assert response.status_code == 403

    async with db_test_session_manager() as session:
        repo = AuditRepository(session)
        rows = await repo.list_for_resource(
            resource_type="user", resource_id=logged_in_user.id
        )
        assert rows == []


# --- Provider profiles ownership-subresource ----------------------------


async def _seed_user_profile(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    practice_name: str,
) -> uuid.UUID:
    profile = make_provider_profile(user_id=user_id, practice_name=practice_name)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(profile)
        await session.refresh(profile)
        return profile.id


async def test_get_my_provider_profiles_empty_state(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """`GET /users/me/provider-profiles` renders the empty state when the
    current user owns no profiles."""
    response = await authenticated_client.get("/users/me/provider-profiles")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    tree = HTMLParser(response.text)
    assert tree.css_first("#user-provider-profiles") is None
    empty = tree.css_first("#user-provider-profiles-empty")
    assert empty is not None
    assert "have not created" in empty.text()


async def test_get_my_provider_profiles_lists_owned(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /users/me/provider-profiles` lists the current user's profiles
    with the right hrefs."""
    first_id = await _seed_user_profile(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="First"
    )
    second_id = await _seed_user_profile(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Second"
    )

    response = await authenticated_client.get("/users/me/provider-profiles")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    items = tree.css("#user-provider-profiles > li")
    assert len(items) == 2
    hrefs = {a.attributes.get("href") for a in tree.css("#user-provider-profiles a")}
    assert hrefs == {
        f"/providers/{first_id}",
        f"/providers/{second_id}",
    }


async def test_get_user_provider_profiles_self(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`GET /users/{my_id}/provider-profiles` works for the current user
    (equivalent to the /me alias)."""
    await _seed_user_profile(
        db_test_session_manager, user_id=logged_in_user.id, practice_name="Mine"
    )

    response = await authenticated_client.get(
        f"/users/{logged_in_user.id}/provider-profiles"
    )
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    assert len(tree.css("#user-provider-profiles > li")) == 1


async def test_get_user_provider_profiles_admin_can_view_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin can view another user's provider-profile list."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)
    await _seed_user_profile(
        db_test_session_manager, user_id=target.id, practice_name="Target Practice"
    )

    response = await authenticated_client.get(f"/users/{target.id}/provider-profiles")
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    heading = tree.css_first("#user-provider-profiles-heading")
    assert heading is not None
    assert target.username in heading.text()
    assert len(tree.css("#user-provider-profiles > li")) == 1


async def test_get_user_provider_profiles_non_admin_forbidden_for_other(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """A non-admin user cannot view another user's provider-profile list."""
    target = create_test_user(username=f"target-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(target)

    response = await authenticated_client.get(f"/users/{target.id}/provider-profiles")
    assert response.status_code == 403


async def test_get_user_provider_profiles_404_for_unknown_user(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Admin requesting an unknown user's list gets 404 (not 403)."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)

    response = await authenticated_client.get(
        f"/users/{uuid.uuid4()}/provider-profiles"
    )
    assert response.status_code == 404


async def test_legacy_provider_profiles_prefix_gone(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """The legacy `/provider-profiles*` prefix has been renamed to `/providers*`.
    Requests to the old path no longer match any route."""
    response = await authenticated_client.get("/provider-profiles")
    assert response.status_code == 404
