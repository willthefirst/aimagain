import pytest
from httpx import AsyncClient
import uuid

# Need models and db connection/utils
from sqlalchemy import insert
from sqlalchemy.engine import Connection
from app.models import User, Conversation, Participant

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_conversations_empty(test_client: AsyncClient):
    """Test GET /conversations returns HTML with no conversations message when empty."""
    response = await test_client.get(f"{API_PREFIX}/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Check for specific content indicating emptiness
    # We'll refine this assertion once we see the actual template/response
    assert "No conversations found" in response.text
    assert "<html>" in response.text # Basic structure check


async def test_list_conversations_one_convo(test_client: AsyncClient, db_conn: Connection):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    # --- Setup: Create user, conversation, and participant ---
    user_id = f"user_{uuid.uuid4()}"
    username = f"convo-creator-{uuid.uuid4()}"
    user_data = {"_id": user_id, "username": username, "is_online": True}
    db_conn.execute(insert(User), user_data)

    convo_id = f"conv_{uuid.uuid4()}"
    convo_slug = f"test-convo-{uuid.uuid4()}"
    convo_data = {
        "_id": convo_id,
        "slug": convo_slug,
        "created_by_user_id": user_id,
        "last_activity_at": None # Or set a time
    }
    db_conn.execute(insert(Conversation), convo_data)

    part_id = f"part_{uuid.uuid4()}"
    part_data = {
        "_id": part_id,
        "user_id": user_id,
        "conversation_id": convo_id,
        "status": "joined",
        # Other fields like joined_at can use defaults or be set if needed
    }
    db_conn.execute(insert(Participant), part_data)
    # No commit needed - using dependency override

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Check for conversation details (slug)
    assert convo_slug in response.text
    # Check for participant username (only joined)
    assert username in response.text
    # Check that the "empty" message is NOT present
    assert "No conversations found" not in response.text
    assert "<html>" in response.text # Basic structure check

    # Cleanup is handled by db_conn fixture rollback 