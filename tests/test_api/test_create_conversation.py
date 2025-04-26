# Tests for POST /conversations
import pytest
from httpx import AsyncClient
import uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import func, select
from app.models import User, Conversation, Participant, Message
from app.schemas.participant import ParticipantStatus
from pydantic import BaseModel
from typing import Optional

from test_helpers import create_test_user


# Helper Pydantic models for request/response validation
class ConversationCreateRequest(BaseModel):
    invitee_user_id: str
    initial_message: str


class ConversationResponse(BaseModel):
    id: str
    slug: str
    created_by_user_id: str


pytestmark = pytest.mark.asyncio


async def test_create_conversation_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations successfully creates resources."""
    invitee = create_test_user(username=f"invitee-{uuid.uuid4()}", is_online=True)
    placeholder_user = logged_in_user

    invitee_id: Optional[UUID] = None
    placeholder_user_id: Optional[UUID] = None
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([invitee])
            await session.flush()
            invitee_id = invitee.id
            placeholder_user_id = placeholder_user.id

    assert invitee_id, "Failed to get invitee ID after flush"
    assert placeholder_user_id, "Failed to get placeholder user ID"

    request_data = ConversationCreateRequest(
        invitee_user_id=str(invitee_id), initial_message="Hello there!"
    )

    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )

    assert (
        response.status_code == 201
    ), f"Expected 201, got {response.status_code}, Response: {response.text}"

    response_data = response.json()
    # Validate response schema
    ConversationResponse.model_validate(response_data)
    assert response_data["created_by_user_id"] == str(placeholder_user_id)

    new_convo_id = UUID(response_data["id"])

    # Verify DB state
    async with db_test_session_manager() as session:
        convo = await session.get(Conversation, new_convo_id)
        assert convo is not None
        assert convo.created_by_user_id == placeholder_user_id

        msg_stmt = select(Message).filter(Message.conversation_id == new_convo_id)
        db_message = (await session.execute(msg_stmt)).scalars().first()
        assert db_message is not None
        assert db_message.content == request_data.initial_message
        assert db_message.created_by_user_id == placeholder_user_id
        db_message_id = db_message.id

        part_stmt = select(Participant).filter(
            Participant.conversation_id == new_convo_id
        )
        db_participants = (await session.execute(part_stmt)).scalars().all()
        assert len(db_participants) == 2

        creator_part = next(
            (p for p in db_participants if p.user_id == placeholder_user_id), None
        )
        invitee_part = next(
            (p for p in db_participants if p.user_id == invitee_id), None
        )

        assert creator_part is not None
        assert creator_part.status == ParticipantStatus.JOINED
        assert invitee_part is not None
        assert invitee_part.status == ParticipantStatus.INVITED
        assert invitee_part.invited_by_user_id == placeholder_user_id
        assert invitee_part.initial_message_id == db_message_id


async def test_create_conversation_invitee_not_found(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations returns 404 if invitee_user_id does not exist."""
    non_existent_user_id = uuid.uuid4()
    request_data = ConversationCreateRequest(
        invitee_user_id=str(non_existent_user_id), initial_message="Hello anyone?"
    )
    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )
    assert response.status_code == 404
    detail = response.json().get("detail", "")
    assert (
        "Invitee user with ID" in detail and "not found" in detail
    ), f"Expected detail containing 'Invitee user ... not found', got: {detail}"

    # Verify no conversation created
    async with db_test_session_manager() as session:
        count = (
            await session.execute(select(func.count(Conversation.id)))
        ).scalar_one()
        assert count == 0


async def test_create_conversation_invitee_offline(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations returns 400 if invitee user is not online."""
    invitee = create_test_user(
        username=f"invitee-offline-{uuid.uuid4()}", is_online=False
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(invitee)
            await session.flush()
            invitee_id = invitee.id

    assert invitee_id
    request_data = ConversationCreateRequest(
        invitee_user_id=str(invitee_id), initial_message="Are you there?"
    )
    response = await authenticated_client.post(
        f"/conversations", json=request_data.model_dump()
    )
    assert response.status_code == 400
    assert "Invitee user is not online" in response.json().get("detail", "")

    # Verify no conversation created
    async with db_test_session_manager() as session:
        count = (
            await session.execute(select(func.count(Conversation.id)))
        ).scalar_one()
        assert count == 0
