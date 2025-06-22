import uuid
from typing import Optional
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from src.models import Conversation, Message, Participant, User
from src.schemas.participant import ParticipantResponse, ParticipantStatus

pytestmark = pytest.mark.asyncio


async def test_accept_invitation_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,
):
    """Test PUT /participants/{id} successfully accepts an invitation."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = logged_in_user

    invitation_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"accept-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            initial_message = Message(
                id=uuid.uuid4(),
                content="Accept me!",
                conversation_id=convo_id,
                created_by_user_id=inviter_id,
            )
            session.add(initial_message)
            await session.flush()
            initial_msg_id = initial_message.id

            invitation = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_id,
                initial_message_id=initial_msg_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    # Simulate PUT request with form data
    response = await authenticated_client.put(
        f"/participants/{str(invitation_id)}", data={"status": "joined"}
    )

    assert (
        response.status_code == 200
    ), f"Expected 200 OK, got {response.status_code}: {response.text}"
    response_data = ParticipantResponse(**response.json())
    assert response_data.status == ParticipantStatus.JOINED.value
    assert response_data.id == invitation_id

    # Verify in DB
    async with db_test_session_manager() as session:
        stmt = select(Participant).where(Participant.id == invitation_id)
        result = await session.execute(stmt)
        updated_participant = result.scalars().first()
        assert updated_participant is not None
        assert updated_participant.status == ParticipantStatus.JOINED


async def test_reject_invitation_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,
):
    """Test PUT /participants/{id} successfully rejects an invitation."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = logged_in_user

    invitation_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"reject-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            invitation = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    response = await authenticated_client.put(
        f"/participants/{str(invitation_id)}", data={"status": "rejected"}
    )

    assert response.status_code == 200
    response_data = ParticipantResponse(**response.json())
    assert response_data.status == ParticipantStatus.REJECTED.value

    # Verify in DB
    async with db_test_session_manager() as session:
        stmt = select(Participant).where(Participant.id == invitation_id)
        result = await session.execute(stmt)
        updated_participant = result.scalars().first()
        assert updated_participant is not None
        assert updated_participant.status == ParticipantStatus.REJECTED


async def test_update_participant_not_owned(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,
):
    """Test PUT /participants/{id} returns 403 if participant belongs to another user."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    actual_owner = create_test_user(username=f"owner-{uuid.uuid4()}")

    participant_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter, actual_owner])
            await session.flush()
            inviter_id = inviter.id
            owner_id = actual_owner.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"forbidden-test-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            # Participant belongs to actual_owner
            participant = Participant(
                id=uuid.uuid4(),
                user_id=owner_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_id,
            )
            session.add(participant)
            await session.flush()
            participant_id = participant.id

    assert participant_id

    response = await authenticated_client.put(
        f"/participants/{str(participant_id)}", data={"status": "joined"}
    )

    assert response.status_code == 403, f"Expected 403, got {response.status_code}"


async def test_update_participant_invalid_current_status(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
    logged_in_user: User,
):
    """Test PUT /participants/{id} returns 400 if participant status is not 'invited'."""
    me_user = logged_in_user

    participant_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            await session.flush()
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"status-test-{uuid.uuid4()}",
                created_by_user_id=me_user_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            # Participant is already 'joined'
            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)
            await session.flush()
            participant_id = participant.id

    assert participant_id

    response = await authenticated_client.put(
        f"/participants/{str(participant_id)}", data={"status": "rejected"}
    )

    assert response.status_code == 400, f"Expected 400, got {response.status_code}"


async def test_update_participant_invalid_target_status(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test PUT /participants/{id} returns 400 if target status is invalid."""
    inviter = create_test_user(username=f"inviter-{uuid.uuid4()}")
    me_user = logged_in_user

    invitation_id: Optional[UUID] = None

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([inviter])
            await session.flush()
            inviter_id = inviter.id
            me_user_id = me_user.id

            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"invalid-target-{uuid.uuid4()}",
                created_by_user_id=inviter_id,
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id

            invitation = Participant(
                id=uuid.uuid4(),
                user_id=me_user_id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=inviter_id,
            )
            session.add(invitation)
            await session.flush()
            invitation_id = invitation.id

    assert invitation_id

    # Attempt to set an invalid status using form data
    response = await authenticated_client.put(
        f"/participants/{str(invitation_id)}",
        data={"status": "maybe"},
    )

    # Our custom validation catches invalid status values and returns 400
    assert (
        response.status_code == 400
    ), "Expected 400 Bad Request for invalid status value"


# Tests for rejecting invitation etc. will go here
