# Message polling implementation: TDD approach

## 🎯 Overview

This document outlines the **Test-Driven Development** implementation plan for adding real-time message polling to conversations, following our established testing pyramid and development patterns.

## 🏗️ feature specification

**Goal**: Enable real-time message updates in conversations using smart HTTP polling with caching headers, maintaining HATEOAS compliance.

**User Story**: As a conversation participant, I want to see new messages from other users within 2-3 seconds without manually refreshing the page.

**Technical Approach**:

- Smart polling endpoint with HTTP caching (`If-Modified-Since`, `ETag`)
- HTML fragment responses for new messages
- htmx-powered frontend polling every 2 seconds
- Graceful fallback to manual refresh

## 📋 TDD implementation phases

### **Phase 1: Contract Tests - Testing the Waiter, Not the Chef**

**Objective**: Following the "waiter vs chef" philosophy, verify that htmx clients can communicate correctly with the polling endpoint - focusing on request/response format, headers, and protocol compliance.

#### Step 1.1: Add Constants for Message Polling

Add to `tests/test_contract/constants.py`:

```python
# Message polling constants
CONSUMER_NAME_MESSAGE_POLLING = "message-polling-htmx"
PROVIDER_NAME_MESSAGE_POLLING = "message-polling-api"
PACT_PORT_MESSAGE_POLLING = 1241
MESSAGE_POLLING_PATH = "/conversations/{slug}/messages/updates"
TEST_CONVERSATION_SLUG = "test-conversation-slug"
TEST_HTTP_DATE = "Wed, 21 Oct 2015 07:28:00 GMT"

# Provider states for message polling
PROVIDER_STATE_USER_AUTH_CONVERSATION_EXISTS = "user authenticated and conversation exists"
PROVIDER_STATE_USER_AUTH_NO_NEW_MESSAGES = "user authenticated and no new messages since timestamp"
PROVIDER_STATE_USER_AUTH_NEW_MESSAGES_EXIST = "user authenticated and new messages exist since timestamp"
```

#### Step 1.2: Write Consumer Contract Test (Testing the Waiter)

Create `tests/test_contract/tests/consumer/test_message_polling.py`:

```python
import pytest
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_MESSAGE_POLLING,
    PROVIDER_NAME_MESSAGE_POLLING,
    PACT_PORT_MESSAGE_POLLING,
    TEST_CONVERSATION_SLUG,
    TEST_HTTP_DATE,
    NETWORK_TIMEOUT_MS,
    PROVIDER_STATE_USER_AUTH_CONVERSATION_EXISTS,
    PROVIDER_STATE_USER_AUTH_NO_NEW_MESSAGES,
    PROVIDER_STATE_USER_AUTH_NEW_MESSAGES_EXIST,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

# Test constants
CONVERSATION_PAGE_PATH = f"/conversations/{TEST_CONVERSATION_SLUG}"
MESSAGE_UPDATES_PATH = f"/conversations/{TEST_CONVERSATION_SLUG}/messages/updates"
MOCK_MESSAGE_HTML = '<li class="message" data-message-id="123"><strong>testuser:</strong> New message</li>'

@pytest.mark.contract
@pytest.mark.messages
@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_message_polling_with_new_messages(
    origin_with_routes: str, page: Page
):
    """Contract test: htmx polling request format with new messages response."""
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_MESSAGE_POLLING,
        PROVIDER_NAME_MESSAGE_POLLING,
        port=PACT_PORT_MESSAGE_POLLING,
    )
    mock_server_uri = pact.uri
    conversation_url = f"{origin}{CONVERSATION_PAGE_PATH}"
    mock_polling_url = f"{mock_server_uri}{MESSAGE_UPDATES_PATH}"

    # Define what we expect the htmx client to send (testing the waiter)
    expected_request_headers = {
        "Accept": "text/html, */*",
        "If-Modified-Since": TEST_HTTP_DATE
    }

    # Define what the API should respond with (testing format, not content)
    (
        pact.given(PROVIDER_STATE_USER_AUTH_NEW_MESSAGES_EXIST)
        .upon_receiving("htmx polling request for message updates")
        .with_request(
            method="GET",
            path=MESSAGE_UPDATES_PATH,
            headers=expected_request_headers,
        )
        .will_respond_with(
            status=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "ETag": '"2024-01-01T10:30:00-5"',
                "Last-Modified": "Mon, 01 Jan 2024 15:30:00 GMT",
                "Cache-Control": "no-cache, must-revalidate"
            },
            body=MOCK_MESSAGE_HTML
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=MESSAGE_UPDATES_PATH,
        mock_pact_url=mock_polling_url,
        http_method="GET",
    )

    # Simulate htmx polling (testing the waiter's communication)
    with pact:
        await page.goto(conversation_url)
        # Add htmx attributes to trigger polling
        await page.evaluate(f'''
            const poller = document.createElement('div');
            poller.setAttribute('hx-get', '{MESSAGE_UPDATES_PATH}');
            poller.setAttribute('hx-trigger', 'load');
            poller.setAttribute('hx-headers', '{{"If-Modified-Since": "{TEST_HTTP_DATE}"}}');
            document.body.appendChild(poller);
            htmx.process(poller);
            htmx.trigger(poller, 'load');
        ''')
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

@pytest.mark.contract
@pytest.mark.messages
@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_message_polling_no_updates(
    origin_with_routes: str, page: Page
):
    """Contract test: 304 Not Modified response format."""
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_MESSAGE_POLLING,
        PROVIDER_NAME_MESSAGE_POLLING,
        port=PACT_PORT_MESSAGE_POLLING,
    )
    mock_server_uri = pact.uri
    conversation_url = f"{origin}{CONVERSATION_PAGE_PATH}"
    mock_polling_url = f"{mock_server_uri}{MESSAGE_UPDATES_PATH}"

    # Test 304 response format (testing the waiter understands "no changes")
    (
        pact.given(PROVIDER_STATE_USER_AUTH_NO_NEW_MESSAGES)
        .upon_receiving("htmx polling request with current timestamp")
        .with_request(
            method="GET",
            path=MESSAGE_UPDATES_PATH,
            headers={"If-Modified-Since": TEST_HTTP_DATE},
        )
        .will_respond_with(
            status=304,
            headers={
                "ETag": '"2024-01-01T10:30:00-5"',
                "Cache-Control": "no-cache, must-revalidate"
            }
            # No body for 304 responses
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=MESSAGE_UPDATES_PATH,
        mock_pact_url=mock_polling_url,
        http_method="GET",
    )

    with pact:
        await page.goto(conversation_url)
        await page.evaluate(f'''
            const poller = document.createElement('div');
            poller.setAttribute('hx-get', '{MESSAGE_UPDATES_PATH}');
            poller.setAttribute('hx-trigger', 'load');
            poller.setAttribute('hx-headers', '{{"If-Modified-Since": "{TEST_HTTP_DATE}"}}');
            document.body.appendChild(poller);
            htmx.process(poller);
            htmx.trigger(poller, 'load');
        ''')
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
```

#### Step 1.3: Write Provider Contract Test (Testing API Can Parse)

Create `tests/test_contract/tests/provider/test_message_polling_verification.py`:

```python
import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)

class MessagePollingVerification(BaseProviderVerification):
    """Message polling provider verification following standard pattern."""

    @property
    def provider_name(self) -> str:
        return "message-polling-api"

    @property
    def consumer_name(self) -> str:
        return "message-polling-htmx"

    @property
    def dependency_config(self):
        """Mock only the business logic handler, keep route layer intact."""
        return {
            "src.logic.conversation_processing.handle_get_conversation": {
                "return_value_config": MockDataFactory.create_conversation_with_messages()
            }
        }

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.contract, pytest.mark.provider, pytest.mark.messages]

# Create instance for use in tests
message_polling_verification = MessagePollingVerification()

@create_provider_test_decorator(
    message_polling_verification.dependency_config,
    "with_message_polling_api_mocks"
)
def test_provider_message_polling_pact_verification(provider_server: URL):
    """Verify API can parse htmx polling requests correctly."""
    message_polling_verification.verify_pact(provider_server)
```

#### Step 1.4: Add Mock Data to Factory

Add to `tests/test_contract/tests/shared/mock_data_factory.py`:

```python
@classmethod
def create_conversation_with_messages(cls, **overrides):
    """Create conversation mock with messages for polling tests."""
    conversation = cls.create_conversation(**overrides)

    # Add mock messages
    mock_message = Message(
        id=cls.MOCK_MESSAGE_ID,
        content="Test message content",
        conversation_id=conversation.id,
        created_by_user_id=cls.MOCK_USER_ID,
        created_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
    )
    mock_message.sender = cls.create_user_read(username="testuser")
    conversation.messages = [mock_message]

    return conversation
```

#### Step 1.5: Run Contract Tests (Should Fail)

```bash
pytest -m contract tests/test_contract/tests/consumer/test_message_polling.py -v
# Expected: FAIL - endpoint doesn't exist yet
```

### **Phase 2: API Tests - HTTP Endpoint Behavior**

**Objective**: Define the exact behavior of the polling endpoint with real HTTP requests.

#### Step 2.1: Write Failing API Tests

Create `tests/test_api/test_message_polling.py`:

```python
@pytest.mark.api
async def test_message_polling_endpoint_exists(
    authenticated_client: AsyncClient,
    conversation_with_messages: Conversation
):
    """Test polling endpoint returns 200 for valid conversation."""
    response = await authenticated_client.get(
        f"/conversations/{conversation_with_messages.slug}/messages/updates"
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

@pytest.mark.api
async def test_message_polling_returns_304_when_no_updates(
    authenticated_client: AsyncClient,
    conversation_with_messages: Conversation
):
    """Test 304 Not Modified when client has latest messages."""
    # Get the latest message timestamp
    latest_message = max(conversation_with_messages.messages, key=lambda m: m.created_at)
    timestamp_header = format_http_date(latest_message.created_at)

    response = await authenticated_client.get(
        f"/conversations/{conversation_with_messages.slug}/messages/updates",
        headers={"If-Modified-Since": timestamp_header}
    )

    assert response.status_code == 304
    assert "ETag" in response.headers
    assert response.content == b""  # No body for 304

@pytest.mark.api
async def test_message_polling_returns_new_messages_html(
    authenticated_client: AsyncClient,
    conversation_with_messages: Conversation,
    db_test_session_manager: async_sessionmaker[AsyncSession]
):
    """Test returns HTML fragment when new messages exist."""
    # Get timestamp before adding new message
    old_timestamp = format_http_date(datetime.now() - timedelta(minutes=1))

    # Add a new message to the conversation
    new_message = await add_message_to_conversation(
        conversation_with_messages.id,
        "This is a new message"
    )

    response = await authenticated_client.get(
        f"/conversations/{conversation_with_messages.slug}/messages/updates",
        headers={"If-Modified-Since": old_timestamp}
    )

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "This is a new message" in response.text
    assert '<li class="message"' in response.text
    assert "Last-Modified" in response.headers
    assert "ETag" in response.headers

@pytest.mark.api
async def test_message_polling_requires_authentication(test_client: AsyncClient):
    """Test polling endpoint requires authentication."""
    response = await test_client.get("/conversations/test-slug/messages/updates")
    assert response.status_code == 401

@pytest.mark.api
async def test_message_polling_requires_participant_access(
    authenticated_client: AsyncClient,
    conversation_user_not_participant: Conversation
):
    """Test user must be conversation participant to poll."""
    response = await authenticated_client.get(
        f"/conversations/{conversation_user_not_participant.slug}/messages/updates"
    )
    assert response.status_code == 403

@pytest.mark.api
async def test_message_polling_conversation_not_found(authenticated_client: AsyncClient):
    """Test 404 for non-existent conversation."""
    response = await authenticated_client.get("/conversations/nonexistent/messages/updates")
    assert response.status_code == 404
```

#### Step 2.2: Create Test Fixtures

Add to `tests/test_api/conftest.py`:

```python
@pytest.fixture
async def conversation_with_messages(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User
) -> Conversation:
    """Fixture providing a conversation with test messages."""
    async with db_test_session_manager() as session:
        async with session.begin():
            # Create conversation with logged_in_user as participant
            conversation = create_test_conversation(
                slug="test-conversation-with-messages",
                creator=logged_in_user
            )
            session.add(conversation)
            await session.flush()

            # Add test messages
            message1 = create_test_message(
                conversation_id=conversation.id,
                sender_id=logged_in_user.id,
                content="First message",
                created_at=datetime.now() - timedelta(minutes=5)
            )
            message2 = create_test_message(
                conversation_id=conversation.id,
                sender_id=logged_in_user.id,
                content="Second message",
                created_at=datetime.now() - timedelta(minutes=3)
            )
            session.add_all([message1, message2])

            # Add participant relationship
            participant = create_test_participant(
                user_id=logged_in_user.id,
                conversation_id=conversation.id,
                status=ParticipantStatus.JOINED
            )
            session.add(participant)

    return conversation

@pytest.fixture
async def conversation_user_not_participant(
    db_test_session_manager: async_sessionmaker[AsyncSession]
) -> Conversation:
    """Fixture providing conversation where logged_in_user is NOT a participant."""
    async with db_test_session_manager() as session:
        async with session.begin():
            other_user = create_test_user(username="other-user")
            session.add(other_user)
            await session.flush()

            conversation = create_test_conversation(
                slug="conversation-no-access",
                creator=other_user
            )
            session.add(conversation)

    return conversation

def format_http_date(dt: datetime) -> str:
    """Format datetime as HTTP date string."""
    from email.utils import formatdate
    return formatdate(dt.timestamp(), usegmt=True)

async def add_message_to_conversation(conversation_id: UUID, content: str) -> Message:
    """Helper to add message to conversation during test."""
    # Implementation details for adding message in test
    pass
```

### **Phase 3: Implementation - Make API Tests Pass**

#### Step 3.1: Add Polling Endpoint to Router

Add to `src/api/routes/conversations.py`:

```python
# Add imports
from fastapi import Header
from fastapi.responses import Response
from datetime import datetime, timedelta
from typing import Optional
from email.utils import parsedate_to_datetime, formatdate

@router.get(
    "/conversations/{slug}/messages/updates",
    tags=["conversations", "messages"],
)
async def get_message_updates(
    slug: str,
    request: Request,
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
    if_modified_since: Optional[str] = Header(None, alias="If-Modified-Since"),
):
    """
    Smart polling endpoint for conversation message updates.
    Returns 304 Not Modified if no new messages, or HTML fragment with new messages.
    """
    conversation = await handle_get_conversation(
        slug=slug, requesting_user=user, conv_service=conv_service
    )

    if not conversation:
        return Response(status_code=404)

    # Get the latest message timestamp for ETag generation
    latest_message_time = None
    if conversation.messages:
        latest_message_time = max(msg.created_at for msg in conversation.messages)

    # Create ETag based on latest message timestamp + count
    message_count = len(conversation.messages)
    etag_value = f"{latest_message_time.isoformat() if latest_message_time else 'empty'}-{message_count}"
    etag = f'"{etag_value}"'

    # Parse client's timestamp from If-Modified-Since header
    client_last_seen = None
    if if_modified_since:
        try:
            client_last_seen = parsedate_to_datetime(if_modified_since)
        except (ValueError, TypeError):
            pass

    # Determine if client has the latest version
    if client_last_seen and latest_message_time:
        if latest_message_time <= client_last_seen:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": "no-cache, must-revalidate"
                }
            )

    # Determine which messages to return
    if client_last_seen:
        new_messages = [
            msg for msg in conversation.messages
            if msg.created_at > client_last_seen
        ]
    else:
        new_messages = conversation.messages

    # If no new messages, return 304
    if not new_messages:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": "no-cache, must-revalidate"
            }
        )

    # Return HTML fragment with new messages
    response_headers = {
        "ETag": etag,
        "Cache-Control": "no-cache, must-revalidate"
    }

    if latest_message_time:
        response_headers["Last-Modified"] = formatdate(
            latest_message_time.timestamp(), usegmt=True
        )

    return APIResponse.html_response(
        template_name="conversations/messages_fragment.html",
        context={"messages": new_messages},
        request=request,
        headers=response_headers
    )
```

#### Step 3.2: Create Message Fragment Template

Create `src/templates/conversations/messages_fragment.html`:

```html
{% for msg in messages %}
<li class="message" data-message-id="{{ msg.id }}">
  <strong>{{ msg.sender.username if msg.sender else 'Unknown' }}:</strong>
  {{ msg.content }}
  <span class="message-meta">({{ msg.created_at }})</span>
</li>
{% endfor %}
```

### **Phase 4: frontend integration**

#### Step 4.1: Update Conversation Template

Update `src/templates/conversations/detail.html` to include polling:

```html
{% extends "base.html" %} {% block title %}{{ conversation.name or
conversation.slug }}{% endblock %} {% block head %}
<style>
  #participants-list,
  #messages-list {
    list-style: none;
    padding: 0;
  }
  #messages-list li {
    margin-bottom: 0.5em;
    padding: 0.5em;
    border: 1px solid #eee;
  }
  #messages-list li strong {
    display: inline-block;
    width: 120px;
  }
  .message-meta {
    font-size: 0.8em;
    color: #666;
  }

  /* Visual feedback for new messages */
  .message[data-hx-added] {
    background-color: #f0f8ff;
    animation: highlight 2s ease-out;
  }

  @keyframes highlight {
    from {
      background-color: #e6f3ff;
    }
    to {
      background-color: transparent;
    }
  }
</style>
{% endblock %} {% block content %}
<h1>Conversation: {{ conversation.name or conversation.slug }}</h1>
<p>Slug: {{ conversation.slug }}</p>

<h2>Participants</h2>
<ul id="participants-list">
  {% for p in participants %}
  <li>{{ p.user.username if p.user else 'Unknown' }} ({{ p.status.value }})</li>
  {% else %}
  <li>No participants found.</li>
  {% endfor %}
</ul>

<h2>Messages</h2>
<div id="messages-container">
  <ul id="messages-list">
    {% for msg in messages %}
    <li class="message" data-message-id="{{ msg.id }}">
      <strong>{{ msg.sender.username if msg.sender else 'Unknown' }}:</strong>
      {{ msg.content }}
      <span class="message-meta">({{ msg.created_at }})</span>
    </li>
    {% else %}
    <li>No messages yet.</li>
    {% endfor %}
  </ul>

  <!-- Polling div for new messages -->
  <div
    id="message-poller"
    hx-get="/conversations/{{ conversation.slug }}/messages/updates"
    hx-trigger="every 2s"
    hx-target="#messages-list"
    hx-swap="beforeend"
    hx-headers='{"If-Modified-Since": "{{ latest_message_time if latest_message_time else "" }}"}'></div>
</div>

<hr />
<h2>Send a message</h2>
<form
  action="/conversations/{{ conversation.slug }}/messages"
  method="post"
  name="send-message-form">
  <div>
    <label for="message_content">Your message:</label>
    <textarea
      id="message_content"
      name="message_content"
      rows="3"
      cols="50"
      placeholder="Type your message here..."
      required>
    </textarea>
  </div>
  <br />
  <button type="submit">Send message</button>
</form>

<hr />
<a href="/conversations">Back to conversations</a>
{% endblock %}
```

#### Step 4.2: Update Conversation Route with Timestamp

Update `src/api/routes/conversations.py` `get_conversation` endpoint:

```python
@router.get(
    "/conversations/{slug}",
    tags=["conversations"],
)
async def get_conversation(
    slug: str,
    request: Request,
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Retrieves and displays a specific conversation by calling the handler."""
    conversation = await handle_get_conversation(
        slug=slug, requesting_user=user, conv_service=conv_service
    )

    # Calculate latest message timestamp for polling
    latest_message_time_str = ""
    if conversation and conversation.messages:
        latest_message_time = max(msg.created_at for msg in conversation.messages)
        from email.utils import formatdate
        latest_message_time_str = formatdate(latest_message_time.timestamp(), usegmt=True)

    return APIResponse.html_response(
        template_name="conversations/detail.html",
        context={
            "conversation": conversation,
            "participants": conversation.participants if conversation else [],
            "messages": conversation.messages if conversation else [],
            "latest_message_time": latest_message_time_str,
        },
        request=request,
    )
```

### **Phase 5: Testing Execution Plan**

```bash
# Development workflow - fast feedback
pytest -m "contract or api" tests/ --maxfail=3 -v

# Pre-commit - comprehensive but focused
pytest -m "not integration" tests/ --cov=src --maxfail=1

# CI/CD - full suite with coverage
pytest tests/ --cov=src --cov-report=html --cov-fail-under=85
```

## 🚀 Implementation execution order

1. **Write failing contract tests** → Understand API requirements
2. **Write failing API tests** → Define exact endpoint behavior
3. **Implement minimal endpoint** → Make API tests pass
4. **Update frontend templates** → Enable polling in UI
5. **Run full test suite** → Verify complete feature

## 📋 Success criteria

**Feature complete when**:

- All test layers pass consistently
- Test coverage > 85% for new code
- Manual testing shows 2-3 second message latency
- No performance degradation in existing functionality

This TDD approach ensures:

- ✅ **Clear requirements** defined by tests first
- ✅ **Minimal implementation** that meets exact needs
- ✅ **High confidence** through comprehensive test coverage
- ✅ **Fast feedback loops** during development
- ✅ **Regression protection** for future changes
