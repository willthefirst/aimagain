import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

# Import the session maker type for hinting
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import func, select
from app.models import User, Conversation, Participant, Message
from app.schemas.participant import ParticipantStatus
from selectolax.parser import HTMLParser
from pydantic import BaseModel
from app.schemas.participant import ParticipantResponse  # For type hint/validation
from typing import Optional, AsyncGenerator  # Added AsyncGenerator

from tests.test_helpers import create_test_user

# Removed import of test_async_session_maker
# from tests.conftest import test_async_session_maker


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
    # Depends implicitly on db_test_session_manager via test_client -> test_app -> overrides
    response = await test_client.get(f"/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No conversations found" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_conversations_one_convo(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            await session.flush()

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"test-convo-{uuid.uuid4()}",
                created_by_user_id=user.id,
                last_activity_at=datetime.now(timezone.utc),
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)

    response = await test_client.get(f"/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    convo_items = tree.css("ul > li")
    assert len(convo_items) == 1, "Expected one conversation item"

    item_text = convo_items[0].text()
    assert conversation.slug in item_text, "Conversation slug not found in list item"
    assert user.username in item_text, "Participant username not found in list item"
    assert (
        str(conversation.last_activity_at.year) in item_text
    ), "Last activity year not found"
    assert "No conversations found" not in tree.body.text()


async def test_list_conversations_sorted(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /conversations returns conversations sorted by last_activity_at desc."""
    now = datetime.now(timezone.utc)
    user1 = create_test_user(username=f"user-older-{uuid.uuid4()}")
    user2 = create_test_user(username=f"user-newer-{uuid.uuid4()}")

    convo_older = Conversation(
        id=uuid.uuid4(),
        slug=f"convo-older-{uuid.uuid4()}",
        created_by_user_id=user1.id,
        last_activity_at=now - timedelta(hours=1),
    )
    convo_newer = Conversation(
        id=uuid.uuid4(),
        slug=f"convo-newer-{uuid.uuid4()}",
        created_by_user_id=user2.id,
        last_activity_at=now,
    )

    part_older = Participant(
        id=uuid.uuid4(),
        user_id=user1.id,
        conversation_id=convo_older.id,
        status=ParticipantStatus.JOINED,
    )
    part_newer = Participant(
        id=uuid.uuid4(),
        user_id=user2.id,
        conversation_id=convo_newer.id,
        status=ParticipantStatus.JOINED,
    )

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all(
                [user1, user2, convo_older, convo_newer, part_older, part_newer]
            )

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
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST /conversations successfully creates resources."""
    # creator = create_test_user() # Not needed if logged_in_user is creator
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    # placeholder_user = create_test_user(username="test-user-me") # Removed manual user creation
    placeholder_user = logged_in_user  # Use the user from the fixture

    # Setup initial users
    # creator_id: Optional[UUID] = None # Not needed
    invitee_id: Optional[UUID] = None
    placeholder_user_id: Optional[UUID] = None
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee])  # Only add invitee, placeholder_user exists
            await session.flush()
            # creator_id = creator.id # Not needed
            invitee_id = invitee.id
            placeholder_user_id = placeholder_user.id

    assert invitee_id, "Failed to get invitee ID after flush"
    assert placeholder_user_id, "Failed to get placeholder user ID"

    request_data = ConversationCreateRequest(
        invitee_user_id=str(invitee_id), initial_message="Hello there!"
    )

    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )  # Use authenticated client

    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    assert "id" in response_data
    assert "slug" in response_data
    assert response_data["created_by_user_id"] == str(placeholder_user_id)
    new_convo_id_str = response_data["id"]
    new_convo_slug = response_data["slug"]
    new_convo_id = UUID(new_convo_id_str)

    async with db_test_session_manager() as session:
        convo_stmt = select(Conversation).filter(Conversation.id == new_convo_id)
        convo_result = await session.execute(convo_stmt)
        db_convo = convo_result.scalars().first()
        assert db_convo is not None, "Conversation not found in database"
        assert db_convo.slug == new_convo_slug
        assert db_convo.created_by_user_id == placeholder_user_id

        msg_stmt = select(Message).filter(Message.conversation_id == new_convo_id)
        msg_result = await session.execute(msg_stmt)
        db_message = msg_result.scalars().first()
        assert db_message is not None, "Initial message not found in database"
        assert db_message.content == request_data.initial_message
        assert db_message.created_by_user_id == placeholder_user_id
        db_message_id = db_message.id

        part_stmt = select(Participant).filter(
            Participant.conversation_id == new_convo_id
        )
        part_result = await session.execute(part_stmt)
        db_participants = part_result.scalars().all()
        assert len(db_participants) == 2, "Expected two participants"

        creator_placeholder_part = next(
            (p for p in db_participants if p.user_id == placeholder_user_id), None
        )
        invitee_part = next(
            (p for p in db_participants if p.user_id == invitee_id), None
        )

        assert (
            creator_placeholder_part is not None
        ), "Creator (placeholder) participant record not found"
        assert creator_placeholder_part.status == ParticipantStatus.JOINED

        assert invitee_part is not None, "Invitee participant record not found"
        assert invitee_part.status == ParticipantStatus.INVITED
        assert invitee_part.invited_by_user_id == placeholder_user_id
        assert invitee_part.initial_message_id == db_message_id


async def test_create_conversation_invitee_not_found(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST /conversations returns 404 if invitee_user_id does not exist."""
    # creator = create_test_user() # Not needed
    # placeholder_user = create_test_user(username="test-user-me") # Removed
    # Setup creator
    # async with db_test_session_manager() as session:
    #     async with session.begin():
    #         session.add_all([creator, placeholder_user])
    #         await session.flush()

    non_existent_user_id = uuid.uuid4()

    request_data = ConversationCreateRequest(
        invitee_user_id=str(non_existent_user_id), initial_message="Hello anyone?"
    )

    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )  # Use authenticated client

    assert response.status_code == 404, f"Expected 404, got {response.status_code}"
    # assert "Invitee user not found" in response.json().get(
    #     "detail", ""
    # ), "Error detail mismatch" # Old assertion
    # New assertion: Check if the specific error message substring is present
    detail = response.json().get("detail", "")
    assert (
        "Invitee user with ID" in detail and "not found" in detail
    ), f"Expected detail message containing 'Invitee user with ID ... not found', got: {detail}"

    async with db_test_session_manager() as session:
        count_stmt = select(func.count(Conversation.id))
        count_result = await session.execute(count_stmt)
        count = count_result.scalar_one()
        assert count == 0, "Conversation should not have been created"


async def test_create_conversation_invitee_offline(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST /conversations returns 400 if invitee user is not online."""
    # creator = create_test_user(username=f"creator-{uuid.uuid4()}") # Not needed
    invitee = create_test_user(
        username=f"invitee-offline-{uuid.uuid4()}",
        is_online=False,
    )
    # placeholder_user = create_test_user(username="test-user-me") # Removed
    # Setup users
    invitee_id: Optional[UUID] = None
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee])  # Add invitee
            await session.flush()
            invitee_id = invitee.id

    assert invitee_id

    request_data = ConversationCreateRequest(
        invitee_user_id=str(invitee_id), initial_message="Are you there?"
    )

    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )  # Use authenticated client

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"
    assert "Invitee user is not online" in response.json().get(
        "detail", ""
    ), "Error detail mismatch"

    async with db_test_session_manager() as session:
        count_stmt = select(func.count(Conversation.id))
        count_result = await session.execute(count_stmt)
        count = count_result.scalar_one()
        assert count == 0, "Conversation should not have been created"


# --- Tests for GET /conversations/{slug} ---


async def test_get_conversation_not_found(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient
    logged_in_user: User,  # Need user for auth
):
    """Test GET /conversations/{slug} returns 404 for a non-existent slug."""
    # Implicitly depends on db_test_session_manager via test_client
    non_existent_slug = f"convo-{uuid.uuid4()}"
    response = await authenticated_client.get(
        f"/conversations/{non_existent_slug}"
    )  # Use authenticated client
    assert response.status_code == 404


async def test_get_conversation_forbidden_not_participant(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /conversations/{slug} returns 403 if user is not a participant."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([creator])  # Add creator
            await session.flush()

            # Ensure conversation is created *within* the transaction
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"other-users-convo-{uuid.uuid4()}",
                created_by_user_id=creator.id,
            )
            session.add(conversation)

    response = await authenticated_client.get(
        f"/conversations/{conversation.slug}"
    )  # Use authenticated client

    assert (
        response.status_code == 403
    ), f"Expected 403, got {response.status_code}. Placeholder user 'test-user-me' should exist but not be participant."


async def test_get_conversation_forbidden_invited(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /conversations/{slug} returns 403 if user is participant but status is 'invited'."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user

    conversation = Conversation(
        id=uuid.uuid4(),
        slug=f"invited-status-convo-{uuid.uuid4()}",
        created_by_user_id=inviter.id,
    )

    participant = Participant(
        id=uuid.uuid4(),
        user_id=me_user.id,
        conversation_id=conversation.id,
        status=ParticipantStatus.INVITED,
        invited_by_user_id=inviter.id,
    )

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter])  # Add inviter
            await session.flush()

            conversation.created_by_user_id = inviter.id
            participant.user_id = me_user.id
            participant.invited_by_user_id = inviter.id
            session.add(conversation)
            await session.flush()
            participant.conversation_id = conversation.id
            session.add(participant)

    response = await authenticated_client.get(
        f"/conversations/{conversation.slug}"
    )  # Use authenticated client

    assert response.status_code == 403


async def test_get_conversation_success_joined(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /conversations/{slug} returns details for a joined user."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user
    other_joined = create_test_user(username=f"other-{uuid.uuid4()}")

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([creator, other_joined])  # Add others
            await session.flush()

            conversation = Conversation(
                id=uuid.uuid4(),
                name="Test Chat",
                slug=f"joined-test-convo-{uuid.uuid4()}",
                created_by_user_id=creator.id,
                last_activity_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            session.add(conversation)
            await session.flush()

            msg1 = Message(
                id=uuid.uuid4(),
                content="First message",
                conversation_id=conversation.id,
                created_by_user_id=creator.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=9),
            )
            msg2 = Message(
                id=uuid.uuid4(),
                content="Second message",
                conversation_id=conversation.id,
                created_by_user_id=me_user.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            msg3 = Message(
                id=uuid.uuid4(),
                content="Third message",
                conversation_id=conversation.id,
                created_by_user_id=other_joined.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )

            part_creator = Participant(
                id=uuid.uuid4(),
                user_id=creator.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            part_me = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            part_other = Participant(
                id=uuid.uuid4(),
                user_id=other_joined.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add_all([msg1, msg2, msg3, part_creator, part_me, part_other])

    response = await authenticated_client.get(
        f"/conversations/{conversation.slug}"
    )  # Use authenticated client

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
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST /conversations/{slug}/participants successfully invites a user."""
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user
    invitee_user = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)

    me_user_id: Optional[UUID] = None
    invitee_user_id: Optional[UUID] = None
    convo_id: Optional[UUID] = None
    conversation_slug: str = f"invite-target-convo-{uuid.uuid4()}"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee_user])  # Add invitee
            await session.flush()
            me_user_id = me_user.id
            invitee_user_id = invitee_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=me_user_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            my_participation = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add(my_participation)

    assert me_user_id and invitee_user_id and convo_id

    invite_data = {"invitee_user_id": str(invitee_user_id)}

    response = await authenticated_client.post(  # Use authenticated client
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )

    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    assert response_data["user_id"] == str(invitee_user_id)
    assert response_data["conversation_id"] == str(convo_id)
    assert response_data["status"] == ParticipantStatus.INVITED.value
    assert response_data["invited_by_user_id"] == str(me_user_id)
    assert response_data["initial_message_id"] is None
    new_participant_id_str = response_data["id"]
    new_participant_id = UUID(new_participant_id_str)

    # Verify using async query
    async with db_test_session_manager() as session:
        part_stmt = select(Participant).filter(Participant.id == new_participant_id)
        part_result = await session.execute(part_stmt)
        db_participant = part_result.scalars().first()
        assert db_participant is not None
        assert db_participant.user_id == invitee_user_id
        assert db_participant.conversation_id == convo_id
        assert db_participant.status == ParticipantStatus.INVITED
        assert db_participant.invited_by_user_id == me_user_id
        assert db_participant.initial_message_id is None


async def test_invite_participant_forbidden_not_joined(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST invite returns 403 if requester is not joined."""
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")

    conversation_slug = f"invite-forbidden-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None
    me_user_id: Optional[UUID] = None
    convo_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee, creator])  # Add others
            await session.flush()
            invitee_id = invitee.id
            me_user_id = me_user.id
            creator_id = creator.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            # Add 'me_user' as INVITED, not joined
            my_part = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
            )
            session.add(my_part)

    assert invitee_id

    invite_data = {"invitee_user_id": str(invitee_id)}

    response = await authenticated_client.post(  # Use authenticated client
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )

    assert response.status_code == 403


async def test_invite_participant_conflict_already_participant(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST invite returns 409 if invitee is already a participant."""
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)

    conversation_slug = f"invite-conflict-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None
    me_user_id: Optional[UUID] = None
    convo_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee])  # Add invitee
            await session.flush()
            me_user_id = me_user.id
            invitee_id = invitee.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=me_user_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            my_part = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            invitee_part = Participant(
                id=uuid.uuid4(),
                user_id=invitee_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add_all([my_part, invitee_part])

    assert invitee_id

    invite_data = {"invitee_user_id": str(invitee_id)}

    response = await authenticated_client.post(  # Use authenticated client
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )

    assert response.status_code == 409


async def test_invite_participant_bad_request_offline(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test POST invite returns 400 if invitee is offline."""
    # me_user = create_test_user(username="test-user-me") # Removed
    me_user = logged_in_user  # Use fixture user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=False)

    conversation_slug = f"invite-offline-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None
    me_user_id: Optional[UUID] = None
    convo_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee])  # Add invitee
            await session.flush()
            me_user_id = me_user.id
            invitee_id = invitee.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=me_user_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            my_part = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add(my_part)

    assert invitee_id

    invite_data = {"invitee_user_id": str(invitee_id)}

    response = await authenticated_client.post(  # Use authenticated client
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )

    assert response.status_code == 400
