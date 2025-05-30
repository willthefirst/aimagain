# Message sending: Test implementations

## 🧪 Complete test code examples

This document provides the complete test implementations for the message sending feature, following the TDD workflow outlined in the implementation plan.

---

## 📋 API integration tests

### **File: `tests/test_api/test_send_message.py`**

```python
# Tests for post /conversations/{slug}/messages
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_helpers import create_test_user

from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus

pytestmark = pytest.mark.asyncio


async def test_send_message_conversation_not_found(
    authenticated_client: AsyncClient,
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 403 for non-existent conversation."""
    non_existent_slug = f"convo-{uuid.uuid4()}"
    form_data = {"message_content": "Hello world"}

    response = await authenticated_client.post(
        f"/conversations/{non_existent_slug}/messages",
        data=form_data
    )
    assert response.status_code == 403


async def test_send_message_not_participant(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 403 if user is not a participant."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=f"others-convo-{uuid.uuid4()}",
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()
            convo_slug = conversation.slug

    form_data = {"message_content": "Hello world"}
    response = await authenticated_client.post(
        f"/conversations/{convo_slug}/messages",
        data=form_data
    )
    assert response.status_code == 403


async def test_send_message_invited_status(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 403 if user status is 'invited'."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"invited-status-convo-{uuid.uuid4()}"

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.INVITED,
                invited_by_user_id=creator.id,
            )
            session.add(participant)

    form_data = {"message_content": "Hello world"}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data
    )
    assert response.status_code == 403


async def test_send_message_success(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages successfully creates message and redirects."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"test-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
                last_activity_at=datetime.now(timezone.utc),
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)
            convo_id = conversation.id
            original_activity_time = conversation.last_activity_at

    form_data = {"message_content": "Test message content"}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data,
        follow_redirects=False,
    )

    # Verify redirect
    assert response.status_code == 303
    assert "Location" in response.headers
    assert response.headers["Location"] == f"/conversations/{conversation_slug}"

    # Verify message was created in database
    async with db_test_session_manager() as session:
        msg_stmt = select(Message).filter(Message.conversation_id == convo_id)
        db_message = (await session.execute(msg_stmt)).scalars().first()
        assert db_message is not None
        assert db_message.content == form_data["message_content"]
        assert db_message.created_by_user_id == me_user.id

        # Verify conversation timestamp was updated
        conv_stmt = select(Conversation).filter(Conversation.id == convo_id)
        updated_conv = (await session.execute(conv_stmt)).scalars().first()
        assert updated_conv.last_activity_at is not None
        assert updated_conv.last_activity_at > original_activity_time


@pytest.mark.parametrize("invalid_content", ["", "   ", "\n\t  "])
async def test_send_message_invalid_content(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
    invalid_content: str,
):
    """Test POST /conversations/{slug}/messages returns 400 for invalid content."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"test-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)
            convo_id = conversation.id

    form_data = {"message_content": invalid_content}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data
    )

    assert response.status_code == 400
    assert "Message content cannot be empty" in response.json().get("detail", "")

    # Verify no message was created
    async with db_test_session_manager() as session:
        count = (
            await session.execute(
                select(func.count(Message.id)).filter(Message.conversation_id == convo_id)
            )
        ).scalar_one()
        assert count == 0


async def test_send_message_form_missing_data(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test POST /conversations/{slug}/messages returns 422 if message_content is missing."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"test-convo-{uuid.uuid4()}"

    # Setup conversation with me_user as JOINED participant
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            participant = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(participant)

    # Send request without message_content field
    form_data = {}
    response = await authenticated_client.post(
        f"/conversations/{conversation_slug}/messages",
        data=form_data
    )

    assert response.status_code == 422
    response_data = response.json()
    assert "detail" in response_data
    assert any(
        "message_content" in error.get("loc", []) for error in response_data["detail"]
    )
```

### **Addition to `tests/test_api/test_get_conversation.py`**

```python
async def test_get_conversation_has_message_form(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Test GET /conversations/{slug} includes message form for joined participants."""
    creator = create_test_user(username=f"creator-{uuid.uuid4()}")
    me_user = logged_in_user
    conversation_slug = f"form-test-convo-{uuid.uuid4()}"
    conversation_name = "Test Chat"

    # Setup data
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(creator)
            await session.flush()
            conversation = Conversation(
                id=uuid.uuid4(),
                name=conversation_name,
                slug=conversation_slug,
                created_by_user_id=creator.id,
            )
            session.add(conversation)
            await session.flush()

            part_me = Participant(
                id=uuid.uuid4(),
                user_id=me_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED,
            )
            session.add(part_me)

    response = await authenticated_client.get(f"/conversations/{conversation_slug}")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

    tree = HTMLParser(response.text)

    # Check for message form
    message_form = tree.css_first("form[name='send-message-form']")
    assert message_form is not None, "Message form not found"

    # Check form action
    form_action = message_form.attributes.get("action", "")
    assert f"/conversations/{conversation_slug}/messages" in form_action

    # Check form method
    assert message_form.attributes.get("method", "").lower() == "post"

    # Check for textarea
    textarea = tree.css_first("textarea[name='message_content']")
    assert textarea is not None, "Message content textarea not found"

    # Check for submit button
    submit_button = tree.css_first("form[name='send-message-form'] button[type='submit']")
    assert submit_button is not None, "Submit button not found"
```

---

## 🔄 Contract tests

### **File: `tests/test_contract/tests/consumer/test_message_form.py`**

```python
import pytest
from playwright.async_api import Page
from pydantic_core import ValidationError

from tests.test_contract.infrastructure.utilities.pact_setup import setup_pact
from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory


@pytest.mark.consumer
@pytest.mark.messages
async def test_consumer_send_message_success(page: Page):
    """Test message form submission creates correct Pact contract."""

    pact = setup_pact("send-message-form", "conversations-api")

    # Define the expected interaction
    pact.given("user is joined participant in conversation") \
        .upon_receiving("a request to send a message") \
        .with_request(
            method="POST",
            path="/conversations/test-slug/messages",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="message_content=Hello+world"
        ) \
        .will_respond_with(
            status=303,
            headers={"Location": "/conversations/test-slug"}
        )

    # Test the interaction
    with pact:
        # Navigate to conversation page
        await page.goto("/conversations/test-slug")

        # Fill and submit the message form
        await page.locator("textarea[name='message_content']").fill("Hello world")
        await page.locator("form[name='send-message-form'] button[type='submit']").click()


@pytest.mark.consumer
@pytest.mark.messages
async def test_consumer_send_message_empty_content(page: Page):
    """Test message form submission with empty content."""

    pact = setup_pact("send-message-form", "conversations-api")

    pact.given("user is joined participant in conversation") \
        .upon_receiving("a request to send an empty message") \
        .with_request(
            method="POST",
            path="/conversations/test-slug/messages",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="message_content="
        ) \
        .will_respond_with(
            status=400,
            headers={"Content-Type": "application/json"},
            body={"detail": "Message content cannot be empty."}
        )

    with pact:
        await page.goto("/conversations/test-slug")
        await page.locator("textarea[name='message_content']").fill("")
        await page.locator("form[name='send-message-form'] button[type='submit']").click()
```

### **File: `tests/test_contract/tests/provider/test_messages_verification.py`**

```python
import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)


class MessagesVerification(BaseProviderVerification):
    """Messages provider verification."""

    @property
    def provider_name(self) -> str:
        return "conversations-api"

    @property
    def consumer_name(self) -> str:
        return "send-message-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_message_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.messages]


# Create instance for use in tests
messages_verification = MessagesVerification()


@create_provider_test_decorator(
    messages_verification.dependency_config,
    "with_messages_api_mocks"
)
@pytest.mark.provider
@pytest.mark.messages
def test_provider_messages_pact_verification(provider_server: URL):
    """Verify API can handle consumer's message sending requests."""
    messages_verification.verify_pact(provider_server)
```

### **Addition to `tests/test_contract/tests/shared/mock_data_factory.py`**

```python
@classmethod
def create_message_dependency_config(cls):
    """Create mock config for message endpoints."""
    return {
        "app.logic.conversation_processing.handle_send_message": {
            "return_value_config": cls.create_message()
        }
    }

@classmethod
def create_message(cls, **overrides):
    """Create a Message instance with default or provided values."""
    from app.models.message import Message
    from datetime import datetime, timezone

    return Message(
        id=overrides.get('id', cls.MOCK_MESSAGE_ID),
        content=overrides.get('content', 'Test message'),
        conversation_id=overrides.get('conversation_id', cls.MOCK_CONVERSATION_ID),
        created_by_user_id=overrides.get('created_by_user_id', cls.MOCK_USER_ID),
        created_at=overrides.get('created_at', datetime.now(timezone.utc))
    )
```

---

## 🎯 Test execution commands

### **Individual test execution**

```bash
# Run specific API tests
pytest tests/test_api/test_send_message.py::test_send_message_success -v
pytest tests/test_api/test_send_message.py::test_send_message_not_participant -v
pytest tests/test_api/test_get_conversation.py::test_get_conversation_has_message_form -v

# Run all message sending API tests
pytest tests/test_api/test_send_message.py -v

# Run contract consumer tests
pytest tests/test_contract/tests/consumer/test_message_form.py -v

# Run contract provider tests
pytest tests/test_contract/tests/provider/test_messages_verification.py -v
```

### **Category-based test execution**

```bash
# Run all message-related tests
pytest -m messages -v

# Run all API integration tests
pytest tests/test_api/ -v

# Run all contract tests
pytest tests/test_contract/ -v

# Run full test suite
pytest
```

### **TDD workflow commands**

```bash
# Step 1: Test message form presence
pytest tests/test_api/test_get_conversation.py::test_get_conversation_has_message_form -v

# Step 2: Test basic route functionality
pytest tests/test_api/test_send_message.py::test_send_message_success -v

# Step 3: Test authorization scenarios
pytest tests/test_api/test_send_message.py -k "not_participant or invited_status or conversation_not_found" -v

# Step 4: Test validation scenarios
pytest tests/test_api/test_send_message.py -k "invalid_content or missing_data" -v

# Step 5: Verify refactoring didn't break anything
pytest tests/test_api/test_send_message.py -v

# Step 6-7: Contract tests
pytest tests/test_contract/ -m messages -v
```

---

## 📊 Test coverage matrix

| Scenario                   | API Test                                      | Contract Test                                 | Status Code | Database Check  |
| -------------------------- | --------------------------------------------- | --------------------------------------------- | ----------- | --------------- |
| **Success**                | ✅ `test_send_message_success`                | ✅ `test_consumer_send_message_success`       | 303         | Message created |
| **Not Participant**        | ✅ `test_send_message_not_participant`        | ❌                                            | 403         | No message      |
| **Invited Status**         | ✅ `test_send_message_invited_status`         | ❌                                            | 403         | No message      |
| **Conversation Not Found** | ✅ `test_send_message_conversation_not_found` | ❌                                            | 403         | No message      |
| **Empty Content**          | ✅ `test_send_message_invalid_content`        | ✅ `test_consumer_send_message_empty_content` | 400         | No message      |
| **Missing Data**           | ✅ `test_send_message_form_missing_data`      | ❌                                            | 422         | No message      |
| **Form Presence**          | ✅ `test_get_conversation_has_message_form`   | ❌                                            | 200         | N/A             |

This comprehensive test suite ensures the message sending feature is thoroughly tested at both the API integration level and the contract level, following the established patterns in the codebase.
