import uuid

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import User
from tests.helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


async def test_list_users_empty(
    authenticated_client: AsyncClient,  # Use authenticated client
    logged_in_user: User,  # Need user for exclusion
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
    authenticated_client: AsyncClient,  # Use authenticated client
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Need user for exclusion
):
    """Test GET /users returns HTML listing one other user."""
    test_username = f"test-user-{uuid.uuid4()}"
    other_user = create_test_user(username=test_username)

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(other_user)

    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul > li")
    assert len(user_list_items) == 1, "Expected one user in the list"
    assert (
        test_username in user_list_items[0].text()
    ), "Correct username not found in list item"
    assert (
        logged_in_user.username not in user_list_items[0].text()
    ), "Logged in user should not be listed"
    assert "No users found" not in tree.body.text()


async def test_list_users_multiple_users(
    authenticated_client: AsyncClient,  # Use authenticated client
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Need user for exclusion
):
    """Test GET /users returns HTML listing multiple other users."""
    user1 = create_test_user(username=f"test-user-one-{uuid.uuid4()}")
    user2 = create_test_user(username=f"test-user-two-{uuid.uuid4()}")

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user1, user2])

    response = await authenticated_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul > li")
    assert len(user_list_items) == 2, "Expected two users in the list"

    usernames_found = {item.text() for item in user_list_items}
    assert user1.username in usernames_found, f"{user1.username} not found in list"
    assert user2.username in usernames_found, f"{user2.username} not found in list"
    assert (
        logged_in_user.username not in usernames_found
    ), "Logged in user should not be listed"
    assert "No users found" not in tree.body.text()
