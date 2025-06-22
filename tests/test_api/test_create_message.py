# Tests for POST /conversations/{slug}/messages
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from src.models import Conversation, Message, Participant, User
from src.schemas.participant import ParticipantStatus

pytestmark = pytest.mark.asyncio


async def test_create_message_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages successfully creates message and redirects."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"test-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
                last_activity_at=datetime.now(timezone.utc),
            )
            session.add(conversation)
            await session.flush()
            await session.refresh(conversation)

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)
            convo_id = conversation.id
            original_activity_time = conversation.last_activity_at

    form_data = {"message_content": "Test message content"}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    # Verify redirect
    assert response.status_code == 303
    assert "Location" in response.headers
    assert response.headers["Location"] == f"/conversations/{conversation_slug}"

    # Verify message was created in database
    async with db_test_session_manager() as session:
        msg_stmt = select(Message).filter(Message.conversation_id == convo_id)
        db_message = (await session.execute(msg_stmt)).scalars().first()
        assert db_message is not None
        assert db_message.content == form_data["message_content"]
        assert db_message.created_by_user_id == me_user.id

        # Verify conversation timestamp was updated
        conv_stmt = select(Conversation).filter(Conversation.id == convo_id)
        updated_conv = (await session.execute(conv_stmt)).scalars().first()
        assert updated_conv.last_activity_at is not None
        assert updated_conv.last_activity_at > original_activity_time


async def test_create_message_conversation_not_found(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 404 for non-existent conversation."""
    non_existent_slug = f"nonexistent-{uuid.uuid4()}"
    form_data = {"message_content": "Test message"}

    response = await authenticated_client.post(
        f"/conversations/{non_existent_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    assert response.status_code == 404


async def test_create_message_user_not_participant(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 403 if user is not a participant."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    conversation_slug = f"other-users-convo-{uuid.uuid4()}"

    # Setup conversation without logged_in_user as participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)

    form_data = {"message_content": "Test message"}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    assert response.status_code == 403


async def test_create_message_user_invited_not_joined(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 403 if user is invited but not joined."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"invited-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as INVITED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=creator.id,
            )
            session.add(participant)

    form_data = {"message_content": "Test message"}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    assert response.status_code == 403


async def test_create_message_empty_content(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages handles empty message content."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"test-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)

    # Test with empty content
    form_data = {"message_content": ""}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    # Current behavior: empty messages are allowed and redirect succeeds
    assert response.status_code == 303
    assert "Location" in response.headers
    assert response.headers["Location"] == f"/conversations/{conversation_slug}"

    # Verify empty message was created in database
    async with db_test_session_manager() as session:
        msg_stmt = select(Message).filter(Message.conversation_id == conversation.id)
        db_message = (await session.execute(msg_stmt)).scalars().first()
        assert db_message is not None
        assert db_message.content == ""
        assert db_message.created_by_user_id == me_user.id


async def test_message_sending_integration(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Integration test: Create conversation, send message, verify it appears in conversation view."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"integration-test-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
                name="Integration Test Chat",
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)

    # Step 1: Send a message
    message_content = "Hello from integration test!"
    form_data = {"message_content": message_content}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    # Verify redirect
    assert response.status_code == 303
    assert response.headers["Location"] == f"/conversations/{conversation_slug}"

    # Step 2: Get the conversation page and verify the message appears
    response = await authenticated_client.get(f"/conversations/{conversation_slug}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    # Parse HTML and verify message is displayed
    from selectolax.parser import HTMLParser

    tree = HTMLParser(response.text)

    # Check that our message appears in the messages list
    messages_list = tree.css("#messages-list > li")
    assert len(messages_list) >= 1, "Expected at least one message"

    messages_text = " ".join([m.text() for m in messages_list])
    assert (
        message_content in messages_text
    ), f"Message '{message_content}' not found in conversation"
    assert (
        me_user.username in messages_text
    ), f"Username '{me_user.username}' not found in messages"

    # Verify the message form is still present for sending more messages
    message_form = tree.css_first("form[name='send-message-form']")
    assert message_form is not None, "Message form should still be present"
