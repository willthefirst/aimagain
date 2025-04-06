# tests/test_api/v1/test_me.py
import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session
from selectolax.parser import HTMLParser
import uuid

# Import User model for setup (if needed, maybe not for empty case)
from app.models import User, Conversation, Message, Participant

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_my_invitations_empty(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/invitations returns HTML with no invitations message when empty."""
    # --- Setup: Create a user with the username the placeholder auth expects ---
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add(me_user)
    db_session.flush()

    response = await test_client.get(f"{API_PREFIX}/users/me/invitations")

    # Now expect 200 OK
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No pending invitations" in tree.body.text()
    assert tree.css_first('ul > li') is None # Check list is empty 


async def test_list_my_invitations_one_invitation(test_client: AsyncClient, db_session: Session):
    """Test GET /users/me/invitations shows one pending invitation correctly."""
    # --- Setup ---
    inviter = User(id=f"user_{uuid.uuid4()}", username=f"inviter-{uuid.uuid4()}")
    # Use a predictable username for the placeholder auth logic
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add_all([inviter, me_user])
    db_session.flush()

    # Create conversation and initial message (needed for participant)
    conversation = Conversation(
        id=f"conv_{uuid.uuid4()}",
        slug=f"test-invite-convo-{uuid.uuid4()}",
        created_by_user_id=inviter.id, # Created by inviter
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

    # Create the 'invited' participant record for "me"
    my_invitation = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id, # Belongs to "me"
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=inviter.id,
        initial_message_id=initial_message.id
    )
    db_session.add(my_invitation)
    db_session.flush()

    # --- Action ---
    # The route's placeholder auth should now find 'me_user' based on the fixed username
    response = await test_client.get(f"{API_PREFIX}/users/me/invitations")

    # --- Assertions ---
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    invitation_items = tree.css('ul > li') # Assuming list items in a ul
    assert len(invitation_items) == 1, "Expected one invitation item"

    item_text = invitation_items[0].text()
    print(f"DEBUG: Invitation item text: {item_text}") # Debugging output

    # Check required fields are present
    assert inviter.username in item_text, "Inviter username not found"
    assert conversation.slug in item_text, "Conversation slug not found"
    assert initial_message_content in item_text, "Initial message preview not found"
    # We need the participant ID for accept/reject actions later
    # Check if it's maybe in a form input value or data attribute
    form_node = invitation_items[0].css_first('form') # Assuming a form for accept/reject
    assert form_node is not None, "Form for accept/reject not found"
    # Check for participant ID, e.g., in the form action URL
    assert my_invitation.id in form_node.attributes.get('action', ''), "Participant ID not found in form action"

    # Check emptiness message is NOT present
    assert "No pending invitations" not in tree.body.text() 