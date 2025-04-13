# tests/test_api/v1/test_me.py
import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session
from selectolax.parser import HTMLParser
import uuid

# Import User model for setup (if needed, maybe not for empty case)
from app.models import User, Conversation, Message, Participant
# Import helper
from tests.test_helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_my_invitations_empty(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/invitations returns HTML with no invitations message when empty."""
    # Use a predictable username for the placeholder auth logic
    me_user = create_test_user(username="test-user-me")
    db_session.add(me_user)
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users/me/invitations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No pending invitations" in tree.body.text()
    assert tree.css_first('ul > li') is None


async def test_list_my_invitations_one_invitation(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/invitations shows one pending invitation correctly."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    # Use a predictable username for the placeholder auth logic
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([inviter, me_user])
    db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"test-invite-convo-{uuid.uuid4()}",
        created_by_user_id=inviter.id,
    )
    db_session.add(conversation)
    db_session.flush()

    initial_message_content = "Join my cool chat!"
    initial_message = Message(
        id=f"msg_{uuid.uuid4()}",
        content=initial_message_content,
        conversation_id=conversation.id,
        created_by_user_id=inviter.id
    )
    db_session.add(initial_message)
    db_session.flush()

    my_invitation = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=inviter.id,
        initial_message_id=initial_message.id
    )
    db_session.add(my_invitation)
    db_session.flush()

    # The route's placeholder auth should now find 'me_user' based on the fixed username
    response = await test_client.get(f"{API_PREFIX}/users/me/invitations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    invitation_items = tree.css('ul > li')
    assert len(invitation_items) == 1, "Expected one invitation item"

    item_text = invitation_items[0].text()
    # print(f"DEBUG: Invitation item text: {item_text}") # Keep debug for now if needed

    assert inviter.username in item_text, "Inviter username not found"
    assert conversation.slug in item_text, "Conversation slug not found"
    assert initial_message_content in item_text, "Initial message preview not found"
    # We need the participant ID for accept/reject actions later
    # Check if it's maybe in a form input value or data attribute
    form_node = invitation_items[0].css_first('form')
    assert form_node is not None, "Form for accept/reject not found"
    # Check for participant ID, e.g., in the form action URL
    assert my_invitation.id in form_node.attributes.get('action', ''), "Participant ID not found in form action"

    assert "No pending invitations" not in tree.body.text()

# --- Tests for GET /users/me/conversations ---

async def test_list_my_conversations_empty(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/conversations returns empty when user has no conversations."""
    me_user = create_test_user(username="test-user-me")
    db_session.add(me_user)
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users/me/conversations")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    assert "You are not part of any conversations yet" in tree.body.text()
    assert tree.css_first('ul > li') is None


async def test_list_my_conversations_one_joined(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/conversations shows one conversation where user is joined."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")
    db_session.add_all([creator, me_user])
    db_session.flush()

    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"my-joined-convo-{uuid.uuid4()}",
        name="My Joined Chat",
        created_by_user_id=creator.id
    )
    db_session.add(conversation)
    db_session.flush()

    participant = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="joined"
    )
    db_session.add(participant)
    # Add creator as also joined for realism
    part_creator = Participant(
        id=f"part_c_{uuid.uuid4()}", user_id=creator.id,
        conversation_id=conversation.id, status="joined"
    )
    db_session.add(part_creator)
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users/me/conversations")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    convo_items = tree.css('ul > li')
    assert len(convo_items) == 1, "Expected one conversation item"

    item_text = convo_items[0].text()
    assert conversation.slug in item_text
    assert conversation.name in item_text
    assert me_user.username in item_text
    assert creator.username in item_text
    normalized_text = " ".join(item_text.split())
    assert "My Status: joined" in normalized_text, f"'My Status: joined' not found in normalized text: {normalized_text!r}"
    assert "You are not part of any conversations yet" not in tree.body.text() 