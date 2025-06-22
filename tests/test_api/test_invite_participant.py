# Tests for POST /conversations/{slug}/participants
import uuid
from typing import Optional
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from src.models import Conversation, Participant, User
from src.schemas.participant import ParticipantResponse, ParticipantStatus

pytestmark = pytest.mark.asyncio


async def test_invite_participant_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/participants successfully invites a user."""
    me_user = logged_in_user
    invitee_user = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)

    me_user_id: Optional[UUID] = None
    invitee_user_id: Optional[UUID] = None
    convo_id: Optional[UUID] = None
    conversation_slug: str = f"invite-target-convo-{uuid.uuid4()}"

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(invitee_user)
            await session.flush()
            me_user_id = me_user.id
            invitee_user_id = invitee_user.id
            conversation = Conversation(
                id=uuid.uuid4(), slug=conversation_slug, created_by_user_id=me_user_id
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
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )
    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    # Validate schema
    ParticipantResponse.model_validate(response_data)
    assert response_data["user_id"] == str(invitee_user_id)
    assert response_data["conversation_id"] == str(convo_id)
    assert response_data["status"] == ParticipantStatus.INVITED.value
    assert response_data["invited_by_user_id"] == str(me_user_id)
    assert response_data["initial_message_id"] is None
    new_participant_id = UUID(response_data["id"])

    # Verify DB state
    async with db_test_session_manager() as session:
        db_participant = await session.get(Participant, new_participant_id)
        assert db_participant is not None
        assert db_participant.user_id == invitee_user_id
        assert db_participant.conversation_id == convo_id
        assert db_participant.status == ParticipantStatus.INVITED
        assert db_participant.invited_by_user_id == me_user_id
        assert db_participant.initial_message_id is None


async def test_invite_participant_forbidden_not_joined(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST invite returns 403 if requester is not joined."""
    me_user = logged_in_user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")

    conversation_slug = f"invite-forbidden-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee, creator])
            await session.flush()
            invitee_id = invitee.id
            creator_id = creator.id
            conversation = Conversation(
                id=uuid.uuid4(), slug=conversation_slug, created_by_user_id=creator_id
            )
            session.add(conversation)
            await session.flush()
            convo_id = conversation.id
            my_part = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=convo_id,
                status=ParticipantStatus.INVITED,
            )
            session.add(my_part)

    assert invitee_id
    invite_data = {"invitee_user_id": str(invitee_id)}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )
    assert response.status_code == 403


async def test_invite_participant_conflict_already_participant(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST invite returns 409 if invitee is already a participant."""
    me_user = logged_in_user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)

    conversation_slug = f"invite-conflict-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(invitee)
            await session.flush()
            me_user_id = me_user.id
            invitee_id = invitee.id
            conversation = Conversation(
                id=uuid.uuid4(), slug=conversation_slug, created_by_user_id=me_user_id
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
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )
    assert response.status_code == 409


async def test_invite_participant_bad_request_offline(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST invite returns 400 if invitee is offline."""
    me_user = logged_in_user
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=False)

    conversation_slug = f"invite-offline-{uuid.uuid4()}"
    invitee_id: Optional[UUID] = None

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(invitee)
            await session.flush()
            me_user_id = me_user.id
            invitee_id = invitee.id
            conversation = Conversation(
                id=uuid.uuid4(), slug=conversation_slug, created_by_user_id=me_user_id
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
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/participants", json=invite_data
    )
    assert response.status_code == 400
