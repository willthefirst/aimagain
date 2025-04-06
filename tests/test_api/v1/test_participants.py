# tests/test_api/v1/test_participants.py
import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session
import uuid

from app.models import User, Conversation, Message, Participant
# Add Pydantic
from pydantic import BaseModel

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"

# Placeholder schema
class ParticipantUpdateRequest(BaseModel):
    status: str # 'joined' or 'rejected'

async def test_accept_invitation_success(test_client: AsyncClient, db_session: Session):
    """Test PUT /participants/{id} successfully accepts an invitation."""
    # --- Setup: Create inviter, invitee(me), conversation, message, and invitation ---
    inviter = User(id=f"user_{uuid.uuid4()}", username=f"inviter-{uuid.uuid4()}")
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me") # Use placeholder name
    db_session.add_all([inviter, me_user])
    db_session.flush()

    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"accept-test-{uuid.uuid4()}", created_by_user_id=inviter.id)
    db_session.add(conversation)
    db_session.flush()

    initial_message = Message(id=f"msg_{uuid.uuid4()}", content="Accept me!", conversation_id=conversation.id, created_by_user_id=inviter.id)
    db_session.add(initial_message)
    db_session.flush()

    invitation = Participant(
        id=f"part_{uuid.uuid4()}",
        user_id=me_user.id,
        conversation_id=conversation.id,
        status="invited",
        invited_by_user_id=inviter.id,
        initial_message_id=initial_message.id
    )
    db_session.add(invitation)
    db_session.flush()
    invitation_id = invitation.id # Capture the ID

    request_data = ParticipantUpdateRequest(status="joined")

    # --- Action ---
    # Simulate PUT request (using POST with _method override or directly if client supports)
    # We assume the test client or FastAPI handles the _method override if used.
    # For now, let's assume a direct PUT for simplicity in the test call.
    response = await test_client.put(
        f"{API_PREFIX}/participants/{invitation_id}",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 200, f"Expected 200, got {response.status_code}, Response: {response.text}"

    # Assert response body (optional, depends on what the endpoint returns)
    # response_data = response.json()
    # assert response_data["status"] == "joined"
    # assert response_data["id"] == invitation_id

    # Assert database state
    db_session.refresh(invitation) # Refresh object state from DB
    assert invitation.status == "joined", "Participant status was not updated to joined"
    assert invitation.joined_at is not None, "Participant joined_at was not set"

async def test_reject_invitation_success(test_client: AsyncClient, db_session: Session):
    """Test PUT /participants/{id} successfully rejects an invitation."""
    # --- Setup ---
    inviter = User(id=f"user_{uuid.uuid4()}", username=f"inviter-{uuid.uuid4()}")
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add_all([inviter, me_user])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"reject-test-{uuid.uuid4()}", created_by_user_id=inviter.id)
    db_session.add(conversation)
    db_session.flush()
    invitation = Participant(
        id=f"part_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id,
        status="invited", invited_by_user_id=inviter.id
    )
    db_session.add(invitation)
    db_session.flush()
    invitation_id = invitation.id

    request_data = ParticipantUpdateRequest(status="rejected")

    # --- Action ---
    response = await test_client.put(
        f"{API_PREFIX}/participants/{invitation_id}",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 200
    db_session.refresh(invitation)
    assert invitation.status == "rejected"
    assert invitation.joined_at is None # Should not be set on reject

async def test_update_participant_not_owned(test_client: AsyncClient, db_session: Session):
    """Test PUT /participants/{id} returns 403 if participant belongs to another user."""
    # --- Setup ---
    inviter = User(id=f"user_{uuid.uuid4()}", username=f"inviter-{uuid.uuid4()}")
    actual_owner = User(id=f"user_{uuid.uuid4()}", username=f"owner-{uuid.uuid4()}")
    # "me" user who will make the request (using placeholder auth)
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add_all([inviter, actual_owner, me_user])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"forbidden-test-{uuid.uuid4()}", created_by_user_id=inviter.id)
    db_session.add(conversation)
    db_session.flush()
    # Participant belongs to actual_owner, not me_user
    participant = Participant(
        id=f"part_{uuid.uuid4()}", user_id=actual_owner.id, conversation_id=conversation.id,
        status="invited", invited_by_user_id=inviter.id
    )
    db_session.add(participant)
    db_session.flush()
    participant_id = participant.id

    request_data = ParticipantUpdateRequest(status="joined")

    # --- Action ---
    response = await test_client.put(
        f"{API_PREFIX}/participants/{participant_id}",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 403

async def test_update_participant_invalid_current_status(test_client: AsyncClient, db_session: Session):
    """Test PUT /participants/{id} returns 400 if participant status is not 'invited'."""
    # --- Setup ---
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add(me_user)
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"status-test-{uuid.uuid4()}", created_by_user_id=me_user.id)
    db_session.add(conversation)
    db_session.flush()
    # Participant is already 'joined'
    participant = Participant(
        id=f"part_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id, status="joined"
    )
    db_session.add(participant)
    db_session.flush()
    participant_id = participant.id

    request_data = ParticipantUpdateRequest(status="rejected") # Try to change from joined -> rejected

    # --- Action ---
    response = await test_client.put(
        f"{API_PREFIX}/participants/{participant_id}",
        json=request_data.model_dump()
    )

    # --- Assertions ---
    assert response.status_code == 400

async def test_update_participant_invalid_target_status(test_client: AsyncClient, db_session: Session):
    """Test PUT /participants/{id} returns 400 if target status is invalid."""
    # --- Setup ---
    inviter = User(id=f"user_{uuid.uuid4()}", username=f"inviter-{uuid.uuid4()}")
    me_user = User(id=f"user_{uuid.uuid4()}", username="test-user-me")
    db_session.add_all([inviter, me_user])
    db_session.flush()
    conversation = Conversation(id=f"conv_{uuid.uuid4()}", slug=f"invalid-target-{uuid.uuid4()}", created_by_user_id=inviter.id)
    db_session.add(conversation)
    db_session.flush()
    invitation = Participant(
        id=f"part_{uuid.uuid4()}", user_id=me_user.id, conversation_id=conversation.id,
        status="invited", invited_by_user_id=inviter.id
    )
    db_session.add(invitation)
    db_session.flush()
    invitation_id = invitation.id

    # --- Action --- Attempt to set an invalid status
    response = await test_client.put(
        f"{API_PREFIX}/participants/{invitation_id}",
        json={"status": "maybe"}
    )

    # --- Assertions ---
    # Pydantic might raise 422 if enum validation is added to schema,
    # otherwise our route logic raises 400
    assert response.status_code in [400, 422]

# Tests for rejecting invitation etc. will go here 