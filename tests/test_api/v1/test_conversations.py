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
from app.schemas.participant import ParticipantResponse # For type hint/validation
from typing import Optional

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

def create_test_user(
    id: Optional[str] = None,
    username: Optional[str] = None,
    email: Optional[str] = None,
    hashed_password: Optional[str] = None,
    is_online: bool = True,
    is_active: bool = True,  # Added fastapi-users default
    is_superuser: bool = False, # Added fastapi-users default
    is_verified: bool = True,   # Added fastapi-users default
) -> User:
    """Creates a User instance with default values for testing."""
    unique_suffix = uuid.uuid4()
    return User(
        id=id or f"user_{unique_suffix}",
        username=username or f"testuser_{unique_suffix}",
        email=email or f"test_{unique_suffix}@example.com",
        hashed_password=hashed_password or f"password_{unique_suffix}",
        is_online=is_online,
        is_active=is_active,
        is_superuser=is_superuser,
        is_verified=is_verified,
    )


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
    user = create_test_user()
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
    user1 = create_test_user(username=f"user-older-{uuid.uuid4()}")
    user2 = create_test_user(username=f"user-newer-{uuid.uuid4()}")
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
    creator = create_test_user()
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True) # Mark as online
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
    creator = create_test_user()
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
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    invitee = create_test_user(
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

# --- Tests for GET /conversations/{slug} ---

async def test_get_conversation_not_found(test_client: AsyncClient):
    """Test GET /conversations/{slug} returns 404 for a non-existent slug."""
    non_existent_slug = f"convo-{uuid.uuid4()}"
    response = await test_client.get(f"{API_PREFIX}/conversations/{non_existent_slug}")
    assert response.status_code == 404


async def test_get_conversation_forbidden_not_participant(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations/{slug} returns 403 if user is not a participant."""
    # --- Setup ---
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    # The user making the request (placeholder auth finds this user)
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([creator, me_user])
    db_session.flush()

    # Conversation exists, but 'me_user' is not involved
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"other-users-convo-{uuid.uuid4()}",
        created_by_user_id=creator.id
    )
    db_session.add(conversation)
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations/{conversation.slug}")

    # --- Assertions ---
    assert response.status_code == 403


async def test_get_conversation_forbidden_invited(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations/{slug} returns 403 if user is participant but status is 'invited'."""
    # --- Setup ---
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([inviter, me_user])
    db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invited-status-convo-{uuid.uuid4()}",
        created_by_user_id=inviter.id
    )
    db_session.add(conversation)
    db_session.flush()

    # Participant record exists, but status is 'invited'
    participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=inviter.id
    )
    db_session.add(participant)
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations/{conversation.slug}")

    # --- Assertions ---
    assert response.status_code == 403


async def test_get_conversation_success_joined(test_client: AsyncClient, db_session: Session):
    """Test GET /conversations/{slug} returns details for a joined user."""
    # --- Setup ---
    creator = create_test_user( username=f"creator-{uuid.uuid4()}")
    # Use placeholder username for the user making the request
    me_user = create_test_user( username="test-user-me")
    other_joined = create_test_user( username=f"other-{uuid.uuid4()}")
    db_session.add_all([creator, me_user, other_joined])
    db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        name="Test Chat",
        slug=f"joined-test-convo-{uuid.uuid4()}",
        created_by_user_id=creator.id,
        last_activity_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    db_session.add(conversation)
    db_session.flush()

    # Add messages
    msg1 = Message(id=f"msg1_{uuid.uuid4()}", content="First message", conversation=conversation, sender=creator, created_at=datetime.now(timezone.utc) - timedelta(minutes=9))
    msg2 = Message(id=f"msg2_{uuid.uuid4()}", content="Second message", conversation=conversation, sender=me_user, created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    msg3 = Message(id=f"msg3_{uuid.uuid4()}", content="Third message", conversation=conversation, sender=other_joined, created_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    db_session.add_all([msg1, msg2, msg3])

    # Add participants ('me' and 'other_joined' are joined)
    part_creator = Participant(id=f"part_c_{uuid.uuid4()}", user=creator, conversation=conversation, status="joined")
    part_me = Participant(id=f"part_me_{uuid.uuid4()}", user=me_user, conversation=conversation, status="joined")
    part_other = Participant(id=f"part_o_{uuid.uuid4()}", user=other_joined, conversation=conversation, status="joined")
    db_session.add_all([part_creator, part_me, part_other])
    db_session.flush()

    # --- Action ---
    response = await test_client.get(f"{API_PREFIX}/conversations/{conversation.slug}")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)

    # Check Conversation Details
    assert conversation.name in tree.css_first('h1').text() # Check name in title/header
    assert conversation.slug in tree.body.text()

    # Check Participants List (assuming a list with id 'participants-list')
    participants_list = tree.css('#participants-list > li') # Adjust selector
    assert len(participants_list) == 3, "Expected 3 participants listed"
    participants_text = " ".join([p.text() for p in participants_list])
    assert creator.username in participants_text
    assert me_user.username in participants_text
    assert other_joined.username in participants_text
    assert "(joined)" in participants_text # Check status indication

    # Check Messages List (assuming a list with id 'messages-list')
    messages_list = tree.css('#messages-list > li') # Adjust selector
    assert len(messages_list) == 3, "Expected 3 messages listed"
    messages_text = " ".join([m.text() for m in messages_list])
    assert msg1.content in messages_text
    assert msg2.content in messages_text
    assert msg3.content in messages_text
    assert creator.username in messages_text # Check sender usernames
    assert me_user.username in messages_text
    assert other_joined.username in messages_text

# --- Tests for POST /conversations/{slug}/participants ---

async def test_invite_participant_success(test_client: AsyncClient, db_session: Session):
    """Test POST /conversations/{slug}/participants successfully invites a user."""
    # --- Setup ---
    # User A (me, the inviter, joined)
    me_user = create_test_user(username="test-user-me")
    # User B (invitee, online, not yet participant)
    invitee_user = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    db_session.add_all([me_user, invitee_user])
    db_session.flush()

    # Conversation C
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invite-target-convo-{uuid.uuid4()}",
        created_by_user_id=me_user.id # Created by me for simplicity
    )
    db_session.add(conversation)
    db_session.flush()

    # Add "me" as a joined participant
    my_participation = Participant(
        id=f"part_{uuid.uuid4()}", user_id=me_user.id,
        conversation_id=conversation.id, status="joined"
    )
    db_session.add(my_participation)
    db_session.flush()

    invite_data = {"invitee_user_id": invitee_user.id}

    # --- Action ---
    response = await test_client.post(
        f"{API_PREFIX}/conversations/{conversation.slug}/participants",
        json=invite_data
    )

    # --- Assertions ---
    assert response.status_code == 201, f"Expected 201, got {response.status_code}, Response: {response.text}"

    # Assert response body structure
    response_data = response.json()
    assert response_data["user_id"] == invitee_user.id
    assert response_data["conversation_id"] == conversation.id
    assert response_data["status"] == "invited"
    assert response_data["invited_by_user_id"] == me_user.id
    assert response_data["initial_message_id"] is None
    new_participant_id = response_data["id"]

    # Assert database state
    db_participant = db_session.query(Participant).filter(Participant.id == new_participant_id).first()
    assert db_participant is not None, "New participant record not found in DB"
    assert db_participant.user_id == invitee_user.id
    assert db_participant.conversation_id == conversation.id
    assert db_participant.status == "invited"
    assert db_participant.invited_by_user_id == me_user.id
    assert db_participant.initial_message_id is None


async def test_invite_participant_forbidden_not_joined(test_client: AsyncClient, db_session: Session):
    """Test POST invite returns 403 if requester is not joined."""
    # --- Setup ---
    me_user = create_test_user(username="test-user-me") # Requester
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    db_session.add_all([me_user, invitee, creator])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"invite-forbidden-{uuid.uuid4()}", created_by_user_id=creator.id)
    db_session.add(conversation)
    # Add 'me_user' as INVITED, not joined
    my_part = Participant(id=f"part_me_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id, status="invited")
    db_session.add(my_part)
    db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    # --- Action ---
    response = await test_client.post(f"{API_PREFIX}/conversations/{conversation.slug}/participants", json=invite_data)

    # --- Assertions ---
    assert response.status_code == 403


async def test_invite_participant_conflict_already_participant(test_client: AsyncClient, db_session: Session):
    """Test POST invite returns 409 if invitee is already a participant."""
    # --- Setup ---
    me_user = create_test_user(username="test-user-me")
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    db_session.add_all([me_user, invitee])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"invite-conflict-{uuid.uuid4()}", created_by_user_id=me_user.id)
    db_session.add(conversation)
    # Add "me" as joined
    my_part = Participant(id=f"part_me_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id, status="joined")
    # Add invitee as already joined
    invitee_part = Participant(id=f"part_inv_{uuid.uuid4()}", user_id=invitee.id, conversation_id=conversation.id, status="joined")
    db_session.add_all([my_part, invitee_part])
    db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    # --- Action ---
    response = await test_client.post(f"{API_PREFIX}/conversations/{conversation.slug}/participants", json=invite_data)

    # --- Assertions ---
    assert response.status_code == 409


async def test_invite_participant_bad_request_offline(test_client: AsyncClient, db_session: Session):
    """Test POST invite returns 400 if invitee is offline."""
    # --- Setup ---
    me_user = create_test_user(username="test-user-me")
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=False) # Offline
    db_session.add_all([me_user, invitee])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"invite-offline-{uuid.uuid4()}", created_by_user_id=me_user.id)
    db_session.add(conversation)
    my_part = Participant(id=f"part_me_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id, status="joined")
    db_session.add(my_part)
    db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    # --- Action ---
    response = await test_client.post(f"{API_PREFIX}/conversations/{conversation.slug}/participants", json=invite_data)

    # --- Assertions ---
    assert response.status_code == 400

