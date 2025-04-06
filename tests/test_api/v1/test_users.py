import pytest
from httpx import AsyncClient
import uuid
# Removed unused datetime import

# Import User ORM model
from app.models import User
# Import Session for type hinting
from sqlalchemy.orm import Session
# Removed unused insert, Connection
# Import HTML Parser
from selectolax.parser import HTMLParser

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"

async def test_list_users_empty(test_client: AsyncClient):
    """Test GET /users returns HTML with no users message when empty."""
    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    # Check for emptiness message (e.g., inside a specific element if possible)
    assert "No users found" in tree.body.text()
    # Check for refresh link href
    link_node = tree.css_first(f'a[href*="{API_PREFIX}/users"]') # Find link containing path
    assert link_node is not None, "Refresh link not found"


# Use the db_session fixture
async def test_list_users_one_user(test_client: AsyncClient, db_session: Session):
    """Test GET /users returns HTML listing one user when one exists."""
    test_username = f"test-user-{uuid.uuid4()}"
    user = User(
        id=f"user_{uuid.uuid4()}",
        username=test_username,
        is_online=False
    )
    db_session.add(user)
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    # Find list items (assuming they are in a <ul>, adjust selector as needed)
    user_list_items = tree.css('ul > li')
    assert len(user_list_items) == 1, "Expected one user in the list"
    assert test_username in user_list_items[0].text(), "Correct username not found in list item"
    # Check emptiness message is NOT present
    assert "No users found" not in tree.body.text()


# Use the db_session fixture
async def test_list_users_multiple_users(test_client: AsyncClient, db_session: Session):
    """Test GET /users returns HTML listing multiple users when they exist."""
    user1 = User(
        id=f"user_{uuid.uuid4()}",
        username=f"test-user-one-{uuid.uuid4()}",
        is_online=False
    )
    user2 = User(
        id=f"user_{uuid.uuid4()}",
        username=f"test-user-two-{uuid.uuid4()}",
        is_online=True
    )
    db_session.add_all([user1, user2])
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css('ul > li') # Adjust selector if template is different
    assert len(user_list_items) == 2, "Expected two users in the list"

    # Check usernames are present in the list items (order might vary)
    usernames_found = {item.text() for item in user_list_items}
    assert user1.username in usernames_found, f"{user1.username} not found in list"
    assert user2.username in usernames_found, f"{user2.username} not found in list"
    assert "No users found" not in tree.body.text() 