import pytest
from httpx import AsyncClient
import uuid
from uuid import UUID  # Import UUID

from app.models import User, Conversation, Participant
from app.schemas.participant import ParticipantStatus  # Import enum

# Import session maker type for hinting
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from selectolax.parser import HTMLParser
from tests.test_helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


async def test_list_users_empty(test_client: AsyncClient):
    """Test GET /users returns HTML with no users message when empty."""
    # Implicitly depends on db_test_session_manager via test_client
    response = await test_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    assert "No users found" in tree.body.text()
    link_node = tree.css_first(f'a[href*="/users"]')
    assert link_node is not None, "Refresh link not found"


async def test_list_users_one_user(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /users returns HTML listing one user when one exists."""
    test_username = f"test-user-{uuid.uuid4()}"
    user = create_test_user(username=test_username, is_online=False)

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    response = await test_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul > li")
    assert len(user_list_items) == 1, "Expected one user in the list"
    assert (
        test_username in user_list_items[0].text()
    ), "Correct username not found in list item"
    assert "No users found" not in tree.body.text()


async def test_list_users_multiple_users(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /users returns HTML listing multiple users when they exist."""
    user1 = create_test_user(username=f"test-user-one-{uuid.uuid4()}", is_online=False)
    user2 = create_test_user(username=f"test-user-two-{uuid.uuid4()}", is_online=True)

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user1, user2])

    response = await test_client.get(f"/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)
    user_list_items = tree.css("ul > li")
    assert len(user_list_items) == 2, "Expected two users in the list"

    usernames_found = {item.text() for item in user_list_items}
    assert user1.username in usernames_found, f"{user1.username} not found in list"
    assert user2.username in usernames_found, f"{user2.username} not found in list"
    assert "No users found" not in tree.body.text()


async def test_list_users_participated_empty(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /users?participated_with=me returns empty when no shared convos."""
    me_user = create_test_user(username="test-user-me")
    other_user = create_test_user(username="other-user")

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([me_user, other_user])

    response = await test_client.get(f"/users?participated_with=me")

    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    assert "No users found" in tree.body.text()
    assert tree.css_first("ul > li") is None


async def test_list_users_participated_success(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],  # Inject manager
):
    """Test GET /users?participated_with=me returns correct users."""
    me_user = create_test_user(username="test-user-me")
    user_b = create_test_user(username=f"user-b-{uuid.uuid4()}")  # Shared convo
    user_c = create_test_user(username=f"user-c-{uuid.uuid4()}")  # No shared convo

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([me_user, user_b, user_c])
            await session.flush()
            me_user_id = me_user.id  # UUID object
            user_b_id = user_b.id  # UUID object
            user_c_id = user_c.id  # UUID object

            # Convo 1: me and user_b are joined
            convo1 = Conversation(
                # id=f"conv1_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                slug=f"convo1-{uuid.uuid4()}",
                created_by_user_id=me_user_id,  # Use UUID object
            )
            session.add(convo1)
            await session.flush()
            convo1_id = convo1.id  # UUID object
            part1_me = Participant(
                # id=f"p1m_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                user_id=me_user_id,  # Use UUID object
                conversation_id=convo1_id,  # Use UUID object
                # status="joined",
                status=ParticipantStatus.JOINED,  # Use Enum
            )
            part1_b = Participant(
                # id=f"p1b_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                user_id=user_b_id,  # Use UUID object
                conversation_id=convo1_id,  # Use UUID object
                # status="joined",
                status=ParticipantStatus.JOINED,  # Use Enum
            )
            session.add_all([part1_me, part1_b])

            # Convo 2: me joined, user_c invited (should not count)
            convo2 = Conversation(
                # id=f"conv2_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                slug=f"convo2-{uuid.uuid4()}",
                created_by_user_id=me_user_id,  # Use UUID object
            )
            session.add(convo2)
            await session.flush()
            convo2_id = convo2.id  # UUID object
            part2_me = Participant(
                # id=f"p2m_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                user_id=me_user_id,  # Use UUID object
                conversation_id=convo2_id,  # Use UUID object
                # status="joined",
                status=ParticipantStatus.JOINED,  # Use Enum
            )
            part2_c = Participant(
                # id=f"p2c_{uuid.uuid4()}",
                id=uuid.uuid4(),  # Use UUID object
                user_id=user_c_id,  # Use UUID object
                conversation_id=convo2_id,  # Use UUID object
                # status="invited",
                status=ParticipantStatus.INVITED,  # Use Enum
            )  # Invited only
            session.add_all([part2_me, part2_c])

    response = await test_client.get(f"/users?participated_with=me")

    assert response.status_code == 200
    tree = HTMLParser(response.text)
    user_items = tree.css("ul > li")
    assert len(user_items) == 1, f"Expected 1 user, found {len(user_items)}"

    users_text = " ".join([li.text() for li in user_items])
    assert user_b.username in users_text, "User B (shared convo) not found"
    assert (
        user_c.username not in users_text
    ), "User C (no shared convo) should not be found"
    assert me_user.username not in users_text, "User 'me' should not be listed"
    assert "No users found" not in tree.body.text()
