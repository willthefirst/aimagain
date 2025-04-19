# Tests for GET /conversations
import pytest
from httpx import AsyncClient
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from app.models import User, Conversation, Participant
from app.schemas.participant import ParticipantStatus
from selectolax.parser import HTMLParser

from tests.test_helpers import create_test_user

pytestmark = pytest.mark.asyncio


async def test_list_conversations_empty(test_client: AsyncClient):
    """Test GET /conversations returns HTML with no conversations message when empty."""
    response = await test_client.get(f"/conversations")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    assert "No conversations found" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_conversations_one_convo(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test GET /conversations returns HTML listing one conversation when one exists."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"test-convo-{uuid.uuid4()}",
                created_by_user_id=user.id,
                last_activity_at=datetime.now(timezone.utc),
            )
            session.add(conversation)
            await session.flush()
            participant = Participant(
                id=uuid.uuid4(),
                user_id=user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)

    response = await test_client.get(f"/conversations")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    convo_items = tree.css("ul > li")
    assert len(convo_items) == 1, "Expected one conversation item"
    item_text = convo_items[0].text()
    assert conversation.slug in item_text, "Conversation slug not found in list item"
    assert user.username in item_text, "Participant username not found in list item"
    assert (
        str(conversation.last_activity_at.year) in item_text
    ), "Last activity year not found"
    assert "No conversations found" not in tree.body.text()


async def test_list_conversations_sorted(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Test GET /conversations returns conversations sorted by last_activity_at desc."""
    now = datetime.now(timezone.utc)
    user1 = create_test_user(username=f"user-older-{uuid.uuid4()}")
    user2 = create_test_user(username=f"user-newer-{uuid.uuid4()}")
    convo_older = Conversation(
        id=uuid.uuid4(),
        slug=f"convo-older-{uuid.uuid4()}",
        created_by_user_id=user1.id,
        last_activity_at=now - timedelta(hours=1),
    )
    convo_newer = Conversation(
        id=uuid.uuid4(),
        slug=f"convo-newer-{uuid.uuid4()}",
        created_by_user_id=user2.id,
        last_activity_at=now,
    )
    part_older = Participant(
        id=uuid.uuid4(),
        user_id=user1.id,
        conversation_id=convo_older.id,
        status=ParticipantStatus.JOINED,
    )
    part_newer = Participant(
        id=uuid.uuid4(),
        user_id=user2.id,
        conversation_id=convo_newer.id,
        status=ParticipantStatus.JOINED,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all(
                [user1, user2, convo_older, convo_newer, part_older, part_newer]
            )

    response = await test_client.get(f"/conversations")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    slugs_in_order = [
        item.text().split("Slug:")[1].split()[0] for item in tree.css("ul > li")
    ]
    assert len(slugs_in_order) == 2, "Expected two conversation items"
    assert slugs_in_order[0] == convo_newer.slug, "Newer conversation slug not first"
    assert slugs_in_order[1] == convo_older.slug, "Older conversation slug not second"
