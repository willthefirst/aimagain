# Tests for POST /conversations
import uuid
from typing import Optional
from uuid import UUID

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus


# Helper Pydantic models for request/response validation
class ConversationCreateRequest(BaseModel):
    invitee_username: str
    initial_message: str


class ConversationResponse(BaseModel):
    id: str
    slug: str
    created_by_user_id: str


pytestmark = pytest.mark.asyncio


async def test_create_conversation_invitee_not_found(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations returns 404 if invitee_user_id does not exist."""
    request_data = ConversationCreateRequest(
        invitee_username="nonexistent_user", initial_message="Hello there!"
    )
    response = await authenticated_client.post(
        f"/conversations", data=request_data.model_dump()
    )
    assert response.status_code == 404
    detail = response.json().get("detail", "")
    assert (
        "User with username" in detail and "not found" in detail
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
        invitee_username=invitee.username, initial_message="Are you there?"
    )
    response = await authenticated_client.post(
        f"/conversations", data=request_data.model_dump()
    )
    assert response.status_code == 400
    assert "Invitee user is not online" in response.json().get("detail", "")

    # Verify no conversation created
    async with db_test_session_manager() as session:
        count = (
            await session.execute(select(func.count(Conversation.id)))
        ).scalar_one()
        assert count == 0


async def test_create_conversation_success_with_username(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations with form data successfully creates resources and redirects."""
    invitee_username = f"invitee-form-{uuid.uuid4()}"
    invitee = create_test_user(username=invitee_username, is_online=True)
    creator_user = logged_in_user

    invitee_id: Optional[UUID] = None
    creator_user_id: Optional[UUID] = None
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(invitee)
            await session.flush()  # Ensure invitee gets an ID
            invitee_id = invitee.id
            creator_user_id = creator_user.id

    assert invitee_id, "Failed to get invitee ID"
    assert creator_user_id, "Failed to get creator user ID"

    form_data = {
        "invitee_username": invitee_username,
        "initial_message": "Test message via form",
    }

    response = await authenticated_client.post(
        "/conversations",
        data=form_data,
        # Explicitly setting Content-Type might not be needed if httpx handles data correctly
        # headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,  # Important: We want to check the redirect itself
    )

    assert (
        response.status_code == 303
    ), f"Expected 303 Redirect, got {response.status_code}, Response: {response.text}"
    assert (
        "Location" in response.headers
    ), "Location header missing in redirect response"
    redirect_location = response.headers["Location"]
    assert redirect_location.startswith(
        "/conversations/"
    ), "Redirect location doesn't point to a conversation"

    # Extract slug for DB verification
    new_convo_slug = redirect_location.split("/")[-1]
    assert len(new_convo_slug) > 0, "Could not extract slug from redirect location"

    # Verify DB state
    async with db_test_session_manager() as session:
        # Fetch conversation by slug
        convo_stmt = select(Conversation).filter(Conversation.slug == new_convo_slug)
        convo = (await session.execute(convo_stmt)).scalars().first()
        assert (
            convo is not None
        ), f"Conversation with slug {new_convo_slug} not found in DB"
        assert convo.created_by_user_id == creator_user_id
        new_convo_id = convo.id

        # Fetch message
        msg_stmt = select(Message).filter(Message.conversation_id == new_convo_id)
        db_message = (await session.execute(msg_stmt)).scalars().first()
        assert db_message is not None
        assert db_message.content == form_data["initial_message"]
        assert db_message.created_by_user_id == creator_user_id
        db_message_id = db_message.id

        # Fetch participants
        part_stmt = select(Participant).filter(
            Participant.conversation_id == new_convo_id
        )
        db_participants = (await session.execute(part_stmt)).scalars().all()
        assert len(db_participants) == 2

        creator_part = next(
            (p for p in db_participants if p.user_id == creator_user_id), None
        )
        invitee_part = next(
            (p for p in db_participants if p.user_id == invitee_id), None
        )

        assert creator_part is not None
        assert creator_part.status == ParticipantStatus.JOINED
        assert invitee_part is not None
        assert invitee_part.status == ParticipantStatus.INVITED
        assert invitee_part.invited_by_user_id == creator_user_id
        assert invitee_part.initial_message_id == db_message_id


async def test_create_conversation_form_invalid_username(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations with form data returns 404 if invitee username doesn't exist."""
    form_data = {
        "invitee_username": f"nonexistent-user-{uuid.uuid4()}",
        "initial_message": "Does anyone exist?",
    }

    response = await authenticated_client.post(
        "/conversations",
        data=form_data,
        follow_redirects=False,
    )

    assert (
        response.status_code == 404
    ), f"Expected 404 Not Found, got {response.status_code}, Response: {response.text}"
    detail = response.json().get("detail", "")
    assert (
        "User with username" in detail and "not found" in detail
    ), f"Expected detail containing 'User with username ... not found', got: {detail}"

    # Verify no conversation created
    async with db_test_session_manager() as session:
        count = (
            await session.execute(select(func.count(Conversation.id)))
        ).scalar_one()
        assert count == 0, "Conversation should not have been created"


@pytest.mark.parametrize("missing_field", ["invitee_username", "initial_message"])
async def test_create_conversation_form_missing_data(
    authenticated_client: AsyncClient,
    logged_in_user: User,
    missing_field: str,
):
    """Test POST /conversations with form data returns 422 if data is missing."""
    form_data = {
        "invitee_username": f"test-user-{uuid.uuid4()}",
        "initial_message": "Valid message",
    }
    # Remove the field to test missing data
    del form_data[missing_field]

    response = await authenticated_client.post(
        "/conversations",
        data=form_data,
        follow_redirects=False,
    )

    assert (
        response.status_code == 422
    ), f"Expected 422 Unprocessable Entity, got {response.status_code}, Response: {response.text}"
    response_data = response.json()
    assert "detail" in response_data
    assert any(
        missing_field in error.get("loc", []) for error in response_data["detail"]
    )


async def test_create_conversation_form_unauthenticated(test_client: AsyncClient):
    """Test POST /conversations with form data requires authentication."""
    form_data = {
        "invitee_username": "anyuser",
        "initial_message": "Trying to create unauthenticated",
    }

    response = await test_client.post(
        "/conversations",
        data=form_data,
        follow_redirects=False,
    )

    assert (
        response.status_code == 401
    ), f"Expected 401 Unauthorized, got {response.status_code}, Response: {response.text}"
