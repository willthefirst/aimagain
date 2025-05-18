import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Import helper
from test_helpers import create_test_user

# Import User model for setup (if needed, maybe not for empty case)
from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


async def test_list_my_invitations_empty(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /users/me/invitations returns HTML with no invitations message when empty."""
    # Setup the authenticated user
    # me_user = create_test_user(username="test-user-me") # Removed manual user creation
    # async with db_test_session_manager() as session:
    #     async with session.begin():
    #         session.add(me_user)

    response = await authenticated_client.get(f"/users/me/invitations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No pending invitations" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_my_invitations_one_invitation(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /users/me/invitations shows one pending invitation correctly."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    # me_user = create_test_user(username="test-user-me") # Removed manual user creation
    me_user = logged_in_user  # Use the user from the fixture

    my_invitation_id: Optional[UUID] = None
    conversation_slug: str = f"test-invite-convo-{uuid.uuid4()}"
    initial_message_content = "Join my cool chat!"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter])  # Only add inviter, me_user exists
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            initial_message = Message(
                id=uuid.uuid4(),
                content=initial_message_content,
                conversation_id=convo_id,
                created_by_user_id=inviter_id,
            )
            session.add(initial_message)
            await session.flush()
            initial_msg_id = initial_message.id

            my_invitation = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_id,
                initial_message_id=initial_msg_id,
            )
            session.add(my_invitation)
            await session.flush()
            my_invitation_id = my_invitation.id

    assert my_invitation_id

    response = await authenticated_client.get(f"/users/me/invitations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    invitation_items = tree.css("ul > li")
    assert len(invitation_items) == 1, "Expected one invitation item"

    item_text = invitation_items[0].text()
    assert inviter.username in item_text, "Inviter username not found"
    assert conversation_slug in item_text, "Conversation slug not found"
    assert initial_message_content in item_text, "Initial message preview not found"

    form_node = invitation_items[0].css_first("form")
    assert form_node is not None, "Form for accept/reject not found"
    assert str(my_invitation_id) in form_node.attributes.get(
        "action", ""
    ), "Participant ID not found in form action"

    assert "You have no pending invitations" not in tree.body.text()


# --- Tests for GET /users/me/conversations ---


async def test_list_my_conversations_empty(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /users/me/conversations returns empty when user has no conversations."""
    # me_user = create_test_user(username="test-user-me") # Removed manual user creation
    # async with db_test_session_manager() as session:
    #     async with session.begin():
    #         session.add(me_user)

    response = await authenticated_client.get(f"/users/me/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    assert "You are not part of any conversations yet" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_my_conversations_one_joined(
    authenticated_client: AsyncClient,  # Use authenticated client
    # test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,  # Use logged-in user fixture
):
    """Test GET /users/me/conversations shows one conversation where user is joined."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    # me_user = create_test_user(username="test-user-me") # Removed manual user creation
    me_user = logged_in_user  # Use the user from the fixture

    conversation_slug = f"my-joined-convo-{uuid.uuid4()}"
    conversation_name = "My Joined Chat"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([creator])  # Only add creator, me_user exists
            await session.flush()
            creator_id = creator.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                name=conversation_name,
                created_by_user_id=creator_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            part_creator = Participant(
                id=uuid.uuid4(),
                user_id=creator_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add_all([participant, part_creator])

    response = await authenticated_client.get(f"/users/me/conversations")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    convo_items = tree.css("ul > li")
    assert len(convo_items) == 1, "Expected one conversation item"

    item_text = convo_items[0].text()
    assert conversation_slug in item_text
    assert conversation_name in item_text
    assert me_user.username in item_text
    assert creator.username in item_text
    assert "You are not part of any conversations yet" not in tree.body.text()

    # Check the link points to the correct conversation page
    link_node = convo_items[0].css_first(
        f'a[href*="/conversations/{conversation_slug}"]'
    )
    assert link_node is not None, f"Link to conversation {conversation_slug} not found"


# --- Test Unauthenticated Access ---


async def test_get_my_profile_unauthenticated(
    test_client: AsyncClient,  # Use regular client without auth header
):
    """Test GET /users/me/profile returns 401 Unauthorized without authentication."""
    response = await test_client.get("/users/me/profile")
    assert response.status_code == 401


async def test_list_my_invitations_unauthenticated(
    test_client: AsyncClient,  # Use regular client without auth header
):
    """Test GET /users/me/invitations returns 401 Unauthorized without authentication."""
    response = await test_client.get("/users/me/invitations")
    assert response.status_code == 401


async def test_list_my_conversations_unauthenticated(
    test_client: AsyncClient,  # Use regular client without auth header
):
    """Test GET /users/me/conversations returns 401 Unauthorized without authentication."""
    response = await test_client.get("/users/me/conversations")
    assert response.status_code == 401
