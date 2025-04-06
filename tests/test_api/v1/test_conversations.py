import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone

# Need ORM models and Session
from sqlalchemy.orm import Session
from app.models import User, Conversation, Participant
# Removed unused insert, Connection

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


async def test_list_conversations_one_convo(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    # --- Setup: Create user, conversation, and participant objects ---
    user = User(
        _id=f"user_{uuid.uuid4()}",
        username=f"convo-creator-{uuid.uuid4()}",
        is_online=True
    )
    db_session.add(user)
    db_session.flush() # Flush to get user._id if needed, although we use the object

    conversation = Conversation(
        _id=f"conv_{uuid.uuid4()}",
        slug=f"test-convo-{uuid.uuid4()}",
        created_by_user_id=user._id, # Use the created user's ID
        # We could also assign the user object to conversation.creator if lazy loading is acceptable
        # creator=user, # This would work too due to relationships
        last_activity_at=None
    )
    db_session.add(conversation)
    db_session.flush()

    participant = Participant(
        _id=f"part_{uuid.uuid4()}",
        user_id=user._id,
        conversation_id=conversation._id,
        # Alternatively, assign objects:
        # user=user,
        # conversation=conversation,
        status="joined"
    )
    db_session.add(participant)
    db_session.flush()
    # No commit needed - session rollback handles cleanup

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Check for conversation details (slug)
    assert conversation.slug in response.text
    # Check for participant username (only joined)
    assert user.username in response.text
    # Check that the "empty" message is NOT present
    assert "No conversations found" not in response.text
    assert "<html>" in response.text # Basic structure check

    # Cleanup is handled by db_session fixture rollback 


async def test_list_conversations_sorted(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations returns conversations sorted by last_activity_at desc."""
    # --- Setup ---
    now = datetime.now(timezone.utc)
    user1 = User(_id=f"user_{uuid.uuid4()}", username=f"user-older-{uuid.uuid4()}")
    user2 = User(_id=f"user_{uuid.uuid4()}", username=f"user-newer-{uuid.uuid4()}")
    db_session.add_all([user1, user2])
    db_session.flush()

    # Convo 1: Older activity
    convo_older = Conversation(
        _id=f"conv_{uuid.uuid4()}",
        slug=f"convo-older-{uuid.uuid4()}",
        created_by_user_id=user1._id,
        last_activity_at=now - timedelta(hours=1) # Explicitly older
    )
    # Convo 2: Newer activity
    convo_newer = Conversation(
        _id=f"conv_{uuid.uuid4()}",
        slug=f"convo-newer-{uuid.uuid4()}",
        created_by_user_id=user2._id,
        last_activity_at=now # Explicitly newer
    )
    db_session.add_all([convo_older, convo_newer])
    db_session.flush()

    # Add participants (needed for display, though not strictly for sorting)
    part_older = Participant(_id=f"part_{uuid.uuid4()}", user_id=user1._id, conversation_id=convo_older._id, status="joined")
    part_newer = Participant(_id=f"part_{uuid.uuid4()}", user_id=user2._id, conversation_id=convo_newer._id, status="joined")
    db_session.add_all([part_older, part_newer])
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Check that newer convo slug appears before older convo slug in the text
    response_text = response.text
    index_newer = response_text.find(convo_newer.slug)
    index_older = response_text.find(convo_older.slug)

    assert index_newer != -1, "Newer conversation slug not found in response"
    assert index_older != -1, "Older conversation slug not found in response"
    assert index_newer < index_older, "Conversations are not sorted by last_activity_at descending" 