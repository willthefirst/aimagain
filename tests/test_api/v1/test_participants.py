from pydantic import BaseModel
import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timezone, timedelta

from app.models import User, Conversation, Participant, Message
from app.schemas.participant import ParticipantUpdateRequest, ParticipantResponse

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import select
from tests.test_helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# Placeholder schema
class ParticipantUpdateRequest(BaseModel):
    status: str  # 'joined' or 'rejected'


async def test_accept_invitation_success(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test PUT /participants/{id} successfully accepts an invitation."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")

    invitation_id: str = ""

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter, me_user])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=f"conv_{uuid.uuid4()}",
                slug=f"accept-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            initial_message = Message(
                id=f"msg_{uuid.uuid4()}",
                content="Accept me!",
                conversation_id=convo_id,
                created_by_user_id=inviter_id,
            )
            session.add(initial_message)
            await session.flush()
            initial_msg_id = initial_message.id

            invitation = Participant(
                id=f"part_{uuid.uuid4()}",
                user_id=me_user_id,
                conversation_id=convo_id,
                status="invited",
                invited_by_user_id=inviter_id,
                initial_message_id=initial_msg_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    request_data = ParticipantUpdateRequest(status="joined")

    # Simulate PUT request
    response = await test_client.put(
        f"/participants/{invitation_id}", json=request_data.model_dump()
    )

    assert (
        response.status_code == 200
    ), f"Expected 200 OK, got {response.status_code}: {response.text}"
    response_data = ParticipantResponse(**response.json())
    assert response_data.status == "joined"
    assert response_data.id == invitation_id

    # Verify in DB
    async with db_test_session_manager() as session:
        stmt = select(Participant).where(Participant.id == invitation_id)
        result = await session.execute(stmt)
        updated_participant = result.scalars().first()
        assert updated_participant is not None
        assert updated_participant.status == "joined"


async def test_reject_invitation_success(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test PUT /participants/{id} successfully rejects an invitation."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")

    invitation_id: str = ""

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter, me_user])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=f"conv_{uuid.uuid4()}",
                slug=f"reject-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            invitation = Participant(
                id=f"part_{uuid.uuid4()}",
                user_id=me_user_id,
                conversation_id=convo_id,
                status="invited",
                invited_by_user_id=inviter_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    request_data = ParticipantUpdateRequest(status="rejected")

    response = await test_client.put(
        f"/participants/{invitation_id}", json=request_data.model_dump()
    )

    assert response.status_code == 200
    response_data = ParticipantResponse(**response.json())
    assert response_data.status == "rejected"

    # Verify in DB
    async with db_test_session_manager() as session:
        stmt = select(Participant).where(Participant.id == invitation_id)
        result = await session.execute(stmt)
        updated_participant = result.scalars().first()
        assert updated_participant is not None
        assert updated_participant.status == "rejected"


async def test_update_participant_not_owned(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test PUT /participants/{id} returns 403 if participant belongs to another user."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    actual_owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")

    participant_id: str = ""

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter, actual_owner, me_user])
            await session.flush()
            inviter_id = inviter.id
            owner_id = actual_owner.id

            conversation = Conversation(
                id=f"conv_{uuid.uuid4()}",
                slug=f"forbidden-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            # Participant belongs to actual_owner
            participant = Participant(
                id=f"part_{uuid.uuid4()}",
                user_id=owner_id,
                conversation_id=convo_id,
                status="invited",
                invited_by_user_id=inviter_id,
            )
            session.add(participant)
            await session.flush()
            participant_id = participant.id

    assert participant_id

    request_data = ParticipantUpdateRequest(status="joined")

    response = await test_client.put(
        f"/participants/{participant_id}", json=request_data.model_dump()
    )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"


async def test_update_participant_invalid_current_status(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test PUT /participants/{id} returns 400 if participant status is not 'invited'."""
    me_user = create_test_user(username="test-user-me")

    participant_id: str = ""

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(me_user)
            await session.flush()
            me_user_id = me_user.id

            conversation = Conversation(
                id=f"conv_{uuid.uuid4()}",
                slug=f"status-test-{uuid.uuid4()}",
                created_by_user_id=me_user_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            # Participant is already 'joined'
            participant = Participant(
                id=f"part_{uuid.uuid4()}",
                user_id=me_user_id,
                conversation_id=convo_id,
                status="joined",  # Key part: Already joined
            )
            session.add(participant)
            await session.flush()
            participant_id = participant.id

    assert participant_id

    request_data = ParticipantUpdateRequest(
        status="rejected"
    )  # Try to change from joined -> rejected

    response = await test_client.put(
        f"/participants/{participant_id}", json=request_data.model_dump()
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"


async def test_update_participant_invalid_target_status(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test PUT /participants/{id} returns 400 if target status is invalid."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = create_test_user(username="test-user-me")

    invitation_id: str = ""

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter, me_user])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=f"conv_{uuid.uuid4()}",
                slug=f"invalid-target-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            invitation = Participant(
                id=f"part_{uuid.uuid4()}",
                user_id=me_user_id,
                conversation_id=convo_id,
                status="invited",
                invited_by_user_id=inviter_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    # Attempt to set an invalid status
    response = await test_client.put(
        f"/participants/{invitation_id}",
        json={"status": "maybe"},  # Invalid status value
    )

    # The Pydantic model ParticipantUpdateRequest should cause a 422 error here
    # before it even reaches the custom 400 check in the route.
    assert (
        response.status_code == 422
    ), "Expected 422 Unprocessable Entity for invalid Pydantic model input"


# Tests for rejecting invitation etc. will go here
