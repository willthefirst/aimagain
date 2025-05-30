# Tests for GET /conversations/{slug}
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus

pytestmark = pytest.mark.asyncio


async def test_get_conversation_not_found(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Test GET /conversations/{slug} returns 404 for a non-existent slug."""
    non_existent_slug = f"convo-{uuid.uuid4()}"
    response = await authenticated_client.get(f"/conversations/{non_existent_slug}")
    assert response.status_code == 404


async def test_get_conversation_forbidden_not_participant(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /conversations/{slug} returns 403 if user is not a participant."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"other-users-convo-{uuid.uuid4()}",
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()  # Ensure convo exists before request
            convo_slug = conversation.slug  # Capture slug after potential commit/flush

    response = await authenticated_client.get(f"/conversations/{convo_slug}")
    assert (
        response.status_code == 403
    ), f"Expected 403, got {response.status_code}. Detail: {response.text}"


async def test_get_conversation_forbidden_invited(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /conversations/{slug} returns 403 if user is participant but status is 'invited'."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"invited-status-convo-{uuid.uuid4()}"

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(inviter)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=inviter.id,
            )
            session.add(conversation)
            await session.flush()
            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter.id,
            )
            session.add(participant)

    response = await authenticated_client.get(f"/conversations/{conversation_slug}")
    assert response.status_code == 403


async def test_get_conversation_success_joined(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /conversations/{slug} returns details for a joined user."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    other_joined = create_test_user(username=f"other-{uuid.uuid4()}")
    conversation_slug = f"joined-test-convo-{uuid.uuid4()}"
    conversation_name = "Test Chat"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([creator, other_joined])
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                name=conversation_name,
                slug=conversation_slug,
                created_by_user_id=creator.id,
                last_activity_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            msg1 = Message(
                id=uuid.uuid4(),
                content="First message",
                conversation_id=convo_id,
                created_by_user_id=creator.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=9),
            )
            msg2 = Message(
                id=uuid.uuid4(),
                content="Second message",
                conversation_id=convo_id,
                created_by_user_id=me_user.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
            msg3 = Message(
                id=uuid.uuid4(),
                content="Third message",
                conversation_id=convo_id,
                created_by_user_id=other_joined.id,
                created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            part_creator = Participant(
                id=uuid.uuid4(),
                user_id=creator.id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            part_me = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            part_other = Participant(
                id=uuid.uuid4(),
                user_id=other_joined.id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add_all([msg1, msg2, msg3, part_creator, part_me, part_other])

    response = await authenticated_client.get(f"/conversations/{conversation_slug}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert conversation_name in tree.css_first("h1").text()
    assert conversation_slug in tree.body.text()

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


async def test_get_conversation_has_message_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /conversations/{slug} includes message form for joined participants."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"form-test-convo-{uuid.uuid4()}"
    conversation_name = "Test Chat"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                name=conversation_name,
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            part_me = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(part_me)

    response = await authenticated_client.get(f"/conversations/{conversation_slug}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)

    # Check for message form
    message_form = tree.css_first("form[name='send-message-form']")
    assert message_form is not None, "Message form not found"

    # Check form action
    form_action = message_form.attributes.get("action", "")
    assert f"/conversations/{conversation_slug}/messages" in form_action

    # Check form method
    assert message_form.attributes.get("method", "").lower() == "post"

    # Check for textarea
    textarea = tree.css_first("textarea[name='message_content']")
    assert textarea is not None, "Message content textarea not found"

    # Check for submit button
    submit_button = tree.css_first(
        "form[name='send-message-form'] button[type='submit']"
    )
    assert submit_button is not None, "Submit button not found"
