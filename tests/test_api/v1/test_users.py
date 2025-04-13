import pytest
from httpx import AsyncClient
import uuid
# Removed unused datetime import

# Import User ORM model
from app.models import User, Conversation, Participant
# Import Session for type hinting
from sqlalchemy.orm import Session
# Removed unused insert, Connection
# Import HTML Parser
from selectolax.parser import HTMLParser
# Import the helper function
from tests.test_helpers import create_test_user

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
    # Use helper function, remove id
    user = create_test_user(
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
    # Use helper function, remove id
    user1 = create_test_user(
        username=f"test-user-one-{uuid.uuid4()}",
        is_online=False
    )
    # Use helper function, remove id
    user2 = create_test_user(
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

# --- Tests for GET /users?participated_with=me ---

async def test_list_users_participated_empty(test_client: AsyncClient, db_session: Session):
    """Test GET /users?participated_with=me returns empty when no shared convos."""
    # --- Setup: 'me' user exists, but no shared conversations ---
    # Use helper function, remove id
    me_user = create_test_user(username="test-user-me")
    # Use helper function, remove id
    other_user = create_test_user(username="other-user")
    db_session.add_all([me_user, other_user])
    db_session.flush()
    # Can optionally add a convo where 'me' is invited or other user is joined, but not both joined

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/users?participated_with=me")

    # --- Assertions ---
    assert response.status_code == 200 # Expect 200 because base route exists
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    # Expect empty list or specific message
    assert "No users found" in tree.body.text() # Reuse existing empty message for now
    assert tree.css_first('ul > li') is None

async def test_list_users_participated_success(test_client: AsyncClient, db_session: Session):
    """Test GET /users?participated_with=me returns correct users."""
    # --- Setup ---
    # Use helper function, remove id
    me_user = create_test_user(username="test-user-me")
    # Use helper function, remove id
    user_b = create_test_user(username=f"user-b-{uuid.uuid4()}") # Shared convo
    # Use helper function, remove id
    user_c = create_test_user(username=f"user-c-{uuid.uuid4()}") # No shared convo
    db_session.add_all([me_user, user_b, user_c])
    db_session.flush()

    # Convo 1: me and user_b are joined
    convo1 = Conversation(id=f"conv1_{uuid.uuid4()}", slug=f"convo1-{uuid.uuid4()}", created_by_user_id=me_user.id)
    db_session.add(convo1)
    part1_me = Participant(id=f"p1m_{uuid.uuid4()}", user_id=me_user.id, conversation_id=convo1.id, status="joined")
    part1_b = Participant(id=f"p1b_{uuid.uuid4()}", user_id=user_b.id, conversation_id=convo1.id, status="joined")
    db_session.add_all([part1_me, part1_b])

    # Convo 2: me joined, user_c invited (should not count)
    convo2 = Conversation(id=f"conv2_{uuid.uuid4()}", slug=f"convo2-{uuid.uuid4()}", created_by_user_id=me_user.id)
    db_session.add(convo2)
    part2_me = Participant(id=f"p2m_{uuid.uuid4()}", user_id=me_user.id, conversation_id=convo2.id, status="joined")
    part2_c = Participant(id=f"p2c_{uuid.uuid4()}", user_id=user_c.id, conversation_id=convo2.id, status="invited") # Invited only
    db_session.add_all([part2_me, part2_c])
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/users?participated_with=me")

    # --- Assertions ---
    assert response.status_code == 200
    tree = HTMLParser(response.text)
    user_items = tree.css('ul > li') # Adjust selector if needed
    assert len(user_items) == 1, f"Expected 1 user, found {len(user_items)}"

    users_text = " ".join([li.text() for li in user_items])
    assert user_b.username in users_text, "User B (shared convo) not found"
    assert user_c.username not in users_text, "User C (no shared convo) should not be found"
    assert me_user.username not in users_text, "User 'me' should not be listed"
    assert "No users found" not in tree.body.text() 