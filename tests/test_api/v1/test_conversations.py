import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone

# Need ORM models and Session
from sqlalchemy.orm import Session
from app.models import User, Conversation, Participant, Message
# Import HTML Parser
from selectolax.parser import HTMLParser
# Removed unused insert, Connection
# Add Pydantic
from pydantic import BaseModel

# --- Placeholder Models (can be moved/refined later) ---
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str

class ConversationResponse(BaseModel):
    id: str
    slug: str
    created_by_user_id: str
    # Add other fields as needed
# --- End Placeholder Models ---

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


async def test_create_conversation_success(test_client: AsyncClient, db_session: Session):
    """Test POST /conversations successfully creates resources."""
    # --- Setup ---
    creator = User(id=f"user_{uuid.uuid4()}", username=f"creator-{uuid.uuid4()}")
    invitee = User(id=f"user_{uuid.uuid4()}", username=f"invitee-{uuid.uuid4()}", is_online=True) # Mark as online
    db_session.add_all([creator, invitee])
    db_session.flush()

    request_data = ConversationCreateRequest(
        invitee_user_id=invitee.id,
        initial_message="Hello there!"
    )

    # --- Action ---
    response = await test_client.post(
        f"{API_PREFIX}/conversations",
        json=request_data.model_dump() # Use model_dump for Pydantic v2+
    )

    # --- Assertions ---
    assert response.status_code == 201, f"Expected 201, got {response.status_code}, Response: {response.text}"

    # Assert response body structure (basic check)
    response_data = response.json()
    assert "id" in response_data
    assert "slug" in response_data
    assert response_data["created_by_user_id"] == creator.id
    new_convo_id = response_data["id"]
    new_convo_slug = response_data["slug"]

    # Assert database state
    # Fetch conversation using the ID from the response
    db_convo = db_session.query(Conversation).filter(Conversation.id == new_convo_id).first()
    assert db_convo is not None, "Conversation not found in database"
    assert db_convo.slug == new_convo_slug
    assert db_convo.created_by_user_id == creator.id

    # Fetch initial message
    # Assuming only one message exists for this new convo
    db_message = db_session.query(Message).filter(Message.conversation_id == new_convo_id).first()
    assert db_message is not None, "Initial message not found in database"
    assert db_message.content == request_data.initial_message
    assert db_message.created_by_user_id == creator.id

    # Fetch participants
    db_participants = db_session.query(Participant).filter(Participant.conversation_id == new_convo_id).all()
    assert len(db_participants) == 2, "Expected two participants"

    creator_part = next((p for p in db_participants if p.user_id == creator.id), None)
    invitee_part = next((p for p in db_participants if p.user_id == invitee.id), None)

    assert creator_part is not None, "Creator participant record not found"
    assert creator_part.status == "joined"

    assert invitee_part is not None, "Invitee participant record not found"
    assert invitee_part.status == "invited"
    assert invitee_part.invited_by_user_id == creator.id
    assert invitee_part.initial_message_id == db_message.id # Check link to initial message


async def test_create_conversation_invitee_not_found(test_client: AsyncClient, db_session: Session):
    """Test POST /conversations returns 404 if invitee_user_id does not exist."""
    # --- Setup ---
    creator = User(id=f"user_{uuid.uuid4()}", username=f"creator-{uuid.uuid4()}")
    db_session.add(creator)
    db_session.flush()

    non_existent_user_id = f"user_{uuid.uuid4()}" # ID that definitely won't exist

    request_data = ConversationCreateRequest(
        invitee_user_id=non_existent_user_id,
        initial_message="Hello anyone?"
    )

    # --- Action ---
    response = await test_client.post(
        f"{API_PREFIX}/conversations",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 404, f"Expected 404, got {response.status_code}"

    # Assert response detail (optional but good)
    assert "Invitee user not found" in response.json().get("detail", ""), "Error detail mismatch"

    # Assert no conversation was created
    count = db_session.query(Conversation).count()
    assert count == 0, "Conversation should not have been created"


async def test_create_conversation_invitee_offline(test_client: AsyncClient, db_session: Session):
    """Test POST /conversations returns 400 if invitee user is not online."""
    # --- Setup ---
    creator = User(id=f"user_{uuid.uuid4()}", username=f"creator-{uuid.uuid4()}")
    invitee = User(
        id=f"user_{uuid.uuid4()}",
        username=f"invitee-offline-{uuid.uuid4()}",
        is_online=False # Explicitly offline
    )
    db_session.add_all([creator, invitee])
    db_session.flush()

    request_data = ConversationCreateRequest(
        invitee_user_id=invitee.id,
        initial_message="Are you there?"
    )

    # --- Action ---
    response = await test_client.post(
        f"{API_PREFIX}/conversations",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert "Invitee user is not online" in response.json().get("detail", ""), "Error detail mismatch"

    # Assert no conversation was created
    count = db_session.query(Conversation).count()
    assert count == 0, "Conversation should not have been created" 