import pytest
from httpx import AsyncClient
import uuid
# Removed unused datetime import

# Import User ORM model
from app.models import User
# Import Session for type hinting
from sqlalchemy.orm import Session
# Removed unused insert, Connection

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"

async def test_list_users_empty(test_client: AsyncClient):
    """Test GET /users returns HTML with no users message when empty."""
    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "No users found" in response.text

    base_url = str(test_client.base_url).rstrip('/')
    expected_url = f"{base_url}{API_PREFIX}/users"
    assert f'href="{expected_url}"' in response.text

    assert "<html>" in response.text


# Use the db_session fixture
async def test_list_users_one_user(test_client: AsyncClient, db_session: Session):
    """Test GET /users returns HTML listing one user when one exists."""
    test_user_id = f"user_{uuid.uuid4()}"
    test_username = f"test-user-{uuid.uuid4()}"

    # --- Setup: Create user ORM object --- 
    user = User(
        _id=test_user_id,
        username=test_username,
        is_online=False
    )
    db_session.add(user)
    db_session.flush() # Flush to ensure user exists for potential foreign keys if needed
    # No commit needed - session rollback handles cleanup

    # --- Action: Call the API endpoint ---
    response = await test_client.get(f"{API_PREFIX}/users")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert test_username in response.text
    assert "No users found" not in response.text
    assert "<html>" in response.text

    # --- Cleanup: Handled automatically by the fixture's rollback ---


# Use the db_session fixture
async def test_list_users_multiple_users(test_client: AsyncClient, db_session: Session):
    """Test GET /users returns HTML listing multiple users when they exist."""
    user1 = User(
        _id=f"user_{uuid.uuid4()}",
        username=f"test-user-one-{uuid.uuid4()}",
        is_online=False
    )
    user2 = User(
        _id=f"user_{uuid.uuid4()}",
        username=f"test-user-two-{uuid.uuid4()}",
        is_online=True
    )

    # --- Setup: Add users to session ---
    db_session.add_all([user1, user2])
    db_session.flush()
    # No commit needed - session rollback handles cleanup

    # --- Action: Call the API endpoint ---
    response = await test_client.get(f"{API_PREFIX}/users")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert user1.username in response.text
    assert user2.username in response.text
    assert "No users found" not in response.text
    assert "<html>" in response.text # Basic structure check

    # --- Cleanup: Handled automatically by the fixture's rollback --- 