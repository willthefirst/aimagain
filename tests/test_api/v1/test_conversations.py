import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from app.models import User, Conversation, Participant, Message
from selectolax.parser import HTMLParser
from pydantic import BaseModel
from app.schemas.participant import ParticipantResponse  # For type hint/validation
from typing import Optional

from tests.test_helpers import create_test_user


class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str


class ConversationResponse(BaseModel):
    id: str
    slug: str
    created_by_user_id: str
    # Add other fields as needed


pytestmark = pytest.mark.asyncio


async def test_list_conversations_empty(test_client: AsyncClient):
    """Test GET /conversations returns HTML with no conversations message when empty."""
    response = await test_client.get(f"/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No conversations found" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_conversations_one_convo(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    user = create_test_user()
    db_session.add(user)

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"test-convo-{uuid.uuid4()}",
        created_by_user_id=user.id,
        last_activity_at=datetime.now(timezone.utc),
    )
    db_session.add(conversation)

    participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=user.id,
        conversation_id=conversation.id,
        status="joined",
    )
    db_session.add(participant)

    await db_session.flush()

    response = await test_client.get(f"/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    convo_items = tree.css("ul > li")
    assert len(convo_items) == 1, "Expected one conversation item"

    item_text = convo_items[0].text()
    assert conversation.slug in item_text, "Conversation slug not found in list item"
    assert user.username in item_text, "Participant username not found in list item"
    # Note: Formatting depends on template filter, might need adjustment
    assert (
        str(conversation.last_activity_at.year) in item_text
    ), "Last activity year not found"
    assert "No conversations found" not in tree.body.text()


async def test_list_conversations_sorted(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test GET /conversations returns conversations sorted by last_activity_at desc."""
    now = datetime.now(timezone.utc)
    user1 = create_test_user(username=f"user-older-{uuid.uuid4()}")
    user2 = create_test_user(username=f"user-newer-{uuid.uuid4()}")
    db_session.add_all([user1, user2])

    convo_older = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"convo-older-{uuid.uuid4()}",
        created_by_user_id=user1.id,
        last_activity_at=now - timedelta(hours=1),
    )
    convo_newer = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"convo-newer-{uuid.uuid4()}",
        created_by_user_id=user2.id,
        last_activity_at=now,
    )
    db_session.add_all([convo_older, convo_newer])

    part_older = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=user1.id,
        conversation_id=convo_older.id,
        status="joined",
    )
    part_newer = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=user2.id,
        conversation_id=convo_newer.id,
        status="joined",
    )
    db_session.add_all([part_older, part_newer])

    await db_session.flush()

    response = await test_client.get(f"/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    slugs_in_order = [
        item.text().split("Slug:")[1].split()[0] for item in tree.css("ul > li")
    ]

    assert len(slugs_in_order) == 2, "Expected two conversation items"
    assert slugs_in_order[0] == convo_newer.slug, "Newer conversation slug not first"
    assert slugs_in_order[1] == convo_older.slug, "Older conversation slug not second"


async def test_create_conversation_success(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST /conversations successfully creates resources."""
    creator = create_test_user()
    creator_id = creator.id
    invitee = create_test_user(
        username=f"invitee-{uuid.uuid4()}", is_online=True
    )  # Mark as online
    invitee_id = invitee.id
    db_session.add_all([creator, invitee])
    await db_session.flush()

    request_data = ConversationCreateRequest(
        invitee_user_id=invitee.id, initial_message="Hello there!"
    )

    response = await test_client.post(f"/conversations", json=request_data.model_dump())

    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    assert "id" in response_data
    assert "slug" in response_data
    assert response_data["created_by_user_id"] == creator_id
    new_convo_id = response_data["id"]
    new_convo_slug = response_data["slug"]

    # Verify data in DB using async queries
    convo_stmt = select(Conversation).filter(Conversation.id == new_convo_id)
    convo_result = await db_session.execute(convo_stmt)
    db_convo = convo_result.scalars().first()
    assert db_convo is not None, "Conversation not found in database"
    assert db_convo.slug == new_convo_slug
    assert db_convo.created_by_user_id == creator_id

    # Assuming only one message exists for this new convo
    msg_stmt = select(Message).filter(Message.conversation_id == new_convo_id)
    msg_result = await db_session.execute(msg_stmt)
    db_message = msg_result.scalars().first()
    assert db_message is not None, "Initial message not found in database"
    assert db_message.content == request_data.initial_message
    assert db_message.created_by_user_id == creator_id

    part_stmt = select(Participant).filter(Participant.conversation_id == new_convo_id)
    part_result = await db_session.execute(part_stmt)
    db_participants = part_result.scalars().all()
    assert len(db_participants) == 2, "Expected two participants"

    creator_part = next((p for p in db_participants if p.user_id == creator_id), None)
    invitee_part = next((p for p in db_participants if p.user_id == invitee_id), None)

    assert creator_part is not None, "Creator participant record not found"
    assert creator_part.status == "joined"

    assert invitee_part is not None, "Invitee participant record not found"
    assert invitee_part.status == "invited"
    assert invitee_part.invited_by_user_id == creator_id
    assert (
        invitee_part.initial_message_id == db_message.id
    )  # Check link to initial message


async def test_create_conversation_invitee_not_found(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST /conversations returns 404 if invitee_user_id does not exist."""
    creator = create_test_user()
    db_session.add(creator)
    await db_session.flush()

    non_existent_user_id = f"user_{uuid.uuid4()}"  # ID that definitely won't exist

    request_data = ConversationCreateRequest(
        invitee_user_id=non_existent_user_id, initial_message="Hello anyone?"
    )

    response = await test_client.post(f"/conversations", json=request_data.model_dump())

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    assert "Invitee user not found" in response.json().get(
        "detail", ""
    ), "Error detail mismatch"
    # Check count using async query
    count_stmt = select(func.count(Conversation.id))
    count_result = await db_session.execute(count_stmt)
    count = count_result.scalar_one()
    assert count == 0, "Conversation should not have been created"


async def test_create_conversation_invitee_offline(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST /conversations returns 400 if invitee user is not online."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    invitee = create_test_user(
        username=f"invitee-offline-{uuid.uuid4()}",
        is_online=False,  # Explicitly offline
    )
    db_session.add_all([creator, invitee])
    await db_session.flush()

    request_data = ConversationCreateRequest(
        invitee_user_id=invitee.id, initial_message="Are you there?"
    )

    response = await test_client.post(f"/conversations", json=request_data.model_dump())

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert "Invitee user is not online" in response.json().get(
        "detail", ""
    ), "Error detail mismatch"
    # Check count using async query
    count_stmt = select(func.count(Conversation.id))
    count_result = await db_session.execute(count_stmt)
    count = count_result.scalar_one()
    assert count == 0, "Conversation should not have been created"


# --- Tests for GET /conversations/{slug} ---


async def test_get_conversation_not_found(test_client: AsyncClient):
    """Test GET /conversations/{slug} returns 404 for a non-existent slug."""
    non_existent_slug = f"convo-{uuid.uuid4()}"
    response = await test_client.get(f"/conversations/{non_existent_slug}")
    assert response.status_code == 404


async def test_get_conversation_forbidden_not_participant(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test GET /conversations/{slug} returns 403 if user is not a participant."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    creator.id
    # The user making the request (placeholder auth finds this user)
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([creator, me_user])
    await db_session.flush()

    # Conversation exists, but 'me_user' is not involved
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"other-users-convo-{uuid.uuid4()}",
        created_by_user_id=creator.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    response = await test_client.get(f"/conversations/{conversation.slug}")

    assert response.status_code == 403


async def test_get_conversation_forbidden_invited(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test GET /conversations/{slug} returns 403 if user is participant but status is 'invited'."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([inviter, me_user])
    await db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invited-status-convo-{uuid.uuid4()}",
        created_by_user_id=inviter.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    # Participant record exists, but status is 'invited'
    participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=inviter.id,
    )
    db_session.add(participant)
    await db_session.flush()

    response = await test_client.get(f"/conversations/{conversation.slug}")

    assert response.status_code == 403


async def test_get_conversation_success_joined(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test GET /conversations/{slug} returns details for a joined user."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    # Use placeholder username for the user making the request
    me_user = create_test_user(username="test-user-me")
    other_joined = create_test_user(username=f"other-{uuid.uuid4()}")
    db_session.add_all([creator, me_user, other_joined])
    await db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        name="Test Chat",
        slug=f"joined-test-convo-{uuid.uuid4()}",
        created_by_user_id=creator.id,
        last_activity_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )
    db_session.add(conversation)
    await db_session.flush()

    msg1 = Message(
        id=f"msg1_{uuid.uuid4()}",
        content="First message",
        conversation=conversation,
        sender=creator,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=9),
    )
    msg2 = Message(
        id=f"msg2_{uuid.uuid4()}",
        content="Second message",
        conversation=conversation,
        sender=me_user,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    msg3 = Message(
        id=f"msg3_{uuid.uuid4()}",
        content="Third message",
        conversation=conversation,
        sender=other_joined,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add_all([msg1, msg2, msg3])

    part_creator = Participant(
        id=f"part_c_{uuid.uuid4()}",
        user=creator,
        conversation=conversation,
        status="joined",
    )
    part_me = Participant(
        id=f"part_me_{uuid.uuid4()}",
        user=me_user,
        conversation=conversation,
        status="joined",
    )
    part_other = Participant(
        id=f"part_o_{uuid.uuid4()}",
        user=other_joined,
        conversation=conversation,
        status="joined",
    )
    db_session.add_all([part_creator, part_me, part_other])
    await db_session.flush()

    response = await test_client.get(f"/conversations/{conversation.slug}")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)

    assert conversation.name in tree.css_first("h1").text()
    assert conversation.slug in tree.body.text()

    participants_list = tree.css("#participants-list > li")
    assert len(participants_list) == 3, "Expected 3 participants listed"
    participants_text = " ".join([p.text() for p in participants_list])
    assert creator.username in participants_text
    assert me_user.username in participants_text
    assert other_joined.username in participants_text
    assert "(joined)" in participants_text

    messages_list = tree.css("#messages-list > li")
    assert len(messages_list) == 3, "Expected 3 messages listed"
    messages_text = " ".join([m.text() for m in messages_list])
    assert msg1.content in messages_text
    assert msg2.content in messages_text
    assert msg3.content in messages_text
    assert creator.username in messages_text
    assert me_user.username in messages_text
    assert other_joined.username in messages_text


# --- Tests for POST /conversations/{slug}/participants ---


async def test_invite_participant_success(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST /conversations/{slug}/participants successfully invites a user."""
    # User A (me, the inviter, joined)
    me_user = create_test_user(username="test-user-me")
    # User B (invitee, online, not yet participant)
    invitee_user = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    db_session.add_all([me_user, invitee_user])
    await db_session.flush()

    # Conversation C
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invite-target-convo-{uuid.uuid4()}",
        created_by_user_id=me_user.id,  # Access ID after flush
    )
    db_session.add(conversation)
    await db_session.flush()

    my_participation = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="joined",
    )
    db_session.add(my_participation)
    await db_session.flush()

    # Store the ID before the API call to prevent potential lazy-load issues
    invitee_user_id = invitee_user.id
    me_user_id = me_user.id
    invite_data = {"invitee_user_id": invitee_user_id}

    response = await test_client.post(
        f"/conversations/{conversation.slug}/participants", json=invite_data
    )

    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    # Assert against the stored variable
    assert response_data["user_id"] == invitee_user_id
    assert response_data["conversation_id"] == conversation.id
    assert response_data["status"] == "invited"
    assert response_data["invited_by_user_id"] == me_user_id
    assert response_data["initial_message_id"] is None
    new_participant_id = response_data["id"]

    # Verify using async query
    part_stmt = select(Participant).filter(Participant.id == new_participant_id)
    part_result = await db_session.execute(part_stmt)
    db_participant = part_result.scalars().first()
    assert db_participant is not None
    assert db_participant.user_id == invitee_user_id
    assert db_participant.conversation_id == conversation.id
    assert db_participant.status == "invited"
    assert db_participant.invited_by_user_id == me_user_id
    assert db_participant.initial_message_id is None


async def test_invite_participant_forbidden_not_joined(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST invite returns 403 if requester is not joined."""
    # Requester
    me_user = create_test_user(username="test-user-me")
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    db_session.add_all([me_user, invitee, creator])
    await db_session.flush()
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invite-forbidden-{uuid.uuid4()}",
        created_by_user_id=creator.id,
    )
    db_session.add(conversation)
    # Add 'me_user' as INVITED, not joined
    my_part = Participant(
        id=f"part_me_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="invited",
    )
    db_session.add(my_part)
    await db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    response = await test_client.post(
        f"/conversations/{conversation.slug}/participants", json=invite_data
    )

    assert response.status_code == 403


async def test_invite_participant_conflict_already_participant(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST invite returns 409 if invitee is already a participant."""
    me_user = create_test_user(username="test-user-me")
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    db_session.add_all([me_user, invitee])
    await db_session.flush()
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invite-conflict-{uuid.uuid4()}",
        created_by_user_id=me_user.id,
    )
    db_session.add(conversation)
    my_part = Participant(
        id=f"part_me_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="joined",
    )
    invitee_part = Participant(
        id=f"part_inv_{uuid.uuid4()}",
        user_id=invitee.id,
        conversation_id=conversation.id,
        status="joined",
    )
    db_session.add_all([my_part, invitee_part])
    await db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    response = await test_client.post(
        f"/conversations/{conversation.slug}/participants", json=invite_data
    )

    assert response.status_code == 409


async def test_invite_participant_bad_request_offline(
    test_client: AsyncClient, db_session: AsyncSession
):
    """Test POST invite returns 400 if invitee is offline."""
    me_user = create_test_user(username="test-user-me")
    invitee = create_test_user(
        username=f"invitee-{uuid.uuid4()}", is_online=False
    )  # Offline
    db_session.add_all([me_user, invitee])
    await db_session.flush()
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"invite-offline-{uuid.uuid4()}",
        created_by_user_id=me_user.id,
    )
    db_session.add(conversation)
    my_part = Participant(
        id=f"part_me_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="joined",
    )
    db_session.add(my_part)
    await db_session.flush()

    invite_data = {"invitee_user_id": invitee.id}

    response = await test_client.post(
        f"/conversations/{conversation.slug}/participants", json=invite_data
    )

    assert response.status_code == 400
