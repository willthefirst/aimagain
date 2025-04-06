import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone

# Need ORM models and Session
from sqlalchemy.orm import Session
from app.models import User, Conversation, Participant
# Import HTML Parser
from selectolax.parser import HTMLParser
# Removed unused insert, Connection

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_conversations_empty(test_client: AsyncClient):
    """Test GET /conversations returns HTML with no conversations message when empty."""
    response = await test_client.get(f"{API_PREFIX}/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No conversations found" in tree.body.text()
    # Check that no conversation list items exist (e.g., assuming a <ul> for the list)
    assert tree.css_first('ul > li') is None


async def test_list_conversations_one_convo(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    # --- Setup ---
    user = User(
        id=f"user_{uuid.uuid4()}",
        username=f"convo-creator-{uuid.uuid4()}",
        is_online=True
    )
    db_session.add(user)
    db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"test-convo-{uuid.uuid4()}",
        created_by_user_id=user.id,
        last_activity_at=datetime.now(timezone.utc)
    )
    db_session.add(conversation)
    db_session.flush()

    participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=user.id,
        conversation_id=conversation.id,
        status="joined"
    )
    db_session.add(participant)
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    convo_items = tree.css('ul > li') # Assuming list items in a <ul>
    assert len(convo_items) == 1, "Expected one conversation item"

    item_text = convo_items[0].text()
    assert conversation.slug in item_text, "Conversation slug not found in list item"
    assert user.username in item_text, "Participant username not found in list item"
    # Check last activity time format (basic check)
    # Note: Formatting depends on template filter, might need adjustment
    assert str(conversation.last_activity_at.year) in item_text, "Last activity year not found"
    assert "No conversations found" not in tree.body.text()


async def test_list_conversations_sorted(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations returns conversations sorted by last_activity_at desc."""
    # --- Setup ---
    now = datetime.now(timezone.utc)
    user1 = User(id=f"user_{uuid.uuid4()}", username=f"user-older-{uuid.uuid4()}")
    user2 = User(id=f"user_{uuid.uuid4()}", username=f"user-newer-{uuid.uuid4()}")
    db_session.add_all([user1, user2])
    db_session.flush()

    convo_older = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"convo-older-{uuid.uuid4()}",
        created_by_user_id=user1.id,
        last_activity_at=now - timedelta(hours=1)
    )
    convo_newer = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"convo-newer-{uuid.uuid4()}",
        created_by_user_id=user2.id,
        last_activity_at=now
    )
    db_session.add_all([convo_older, convo_newer])
    db_session.flush()

    part_older = Participant(id=f"part_{uuid.uuid4()}", user_id=user1.id, conversation_id=convo_older.id, status="joined")
    part_newer = Participant(id=f"part_{uuid.uuid4()}", user_id=user2.id, conversation_id=convo_newer.id, status="joined")
    db_session.add_all([part_older, part_newer])
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    # Get slugs from list items in order
    slugs_in_order = [item.text().split('Slug:')[1].split()[0] for item in tree.css('ul > li')]

    assert len(slugs_in_order) == 2, "Expected two conversation items"
    assert slugs_in_order[0] == convo_newer.slug, "Newer conversation slug not first"
    assert slugs_in_order[1] == convo_older.slug, "Older conversation slug not second" 