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

### **Phase 2: API Tests - Route Handler Behavior**

**Objective**: Test the ultra-thin route handler layer to ensure it correctly delegates to business logic handlers and formats responses properly.

#### Step 2.1: Write Route Handler Tests

Create `tests/test_api/test_message_polling.py`:

```python
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.testclient import TestClient

from src.models.message import Message
from src.models.conversation import Conversation
from tests.shared_test_data import create_test_user, create_test_conversation


@pytest.mark.api
@pytest.mark.messages
async def test_message_polling_route_delegates_correctly(
    client: TestClient,
    auth_headers: dict
):
    """Test route handler delegates to business logic handler with correct parameters."""

    # Mock the business logic handler (not the route)
    with patch("src.api.routes.conversations.handle_get_message_updates") as mock_handler:
        mock_handler.return_value = {
            "html_content": "<li>Mock message</li>",
            "etag": "test-etag",
            "last_modified": "Mon, 01 Jan 2024 15:30:00 GMT",
            "has_updates": True
        }

        # Act: Call the route
        response = client.get(
            "/conversations/test-slug/messages/updates",
            headers={
                **auth_headers,
                "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"
            }
        )

        # Assert: Route handler called business logic correctly
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert response.headers["etag"] == "test-etag"
        assert response.headers["last-modified"] == "Mon, 01 Jan 2024 15:30:00 GMT"

        # Verify handler was called with right parameters
        mock_handler.assert_called_once()
        call_args = mock_handler.call_args
        assert call_args[1]["slug"] == "test-slug"
        assert "If-Modified-Since" in str(call_args)

@pytest.mark.api
@pytest.mark.messages
async def test_message_polling_route_handles_no_updates(
    client: TestClient,
    auth_headers: dict
):
    """Test route handler returns 304 when business logic indicates no updates."""

    with patch("src.api.routes.conversations.handle_get_message_updates") as mock_handler:
        mock_handler.return_value = {
            "has_updates": False,
            "etag": "current-etag",
            "last_modified": "Mon, 01 Jan 2024 15:30:00 GMT"
        }

        response = client.get(
            "/conversations/test-slug/messages/updates",
            headers={
                **auth_headers,
                "If-Modified-Since": "Mon, 01 Jan 2024 15:30:00 GMT"
            }
        )

        assert response.status_code == 304
        assert response.text == ""
        assert response.headers["etag"] == "current-etag"

@pytest.mark.api
@pytest.mark.messages
async def test_message_polling_route_requires_authentication(client: TestClient):
    """Test route handler properly enforces authentication."""

    response = client.get("/conversations/test-slug/messages/updates")
    assert response.status_code == 401

@pytest.mark.api
@pytest.mark.messages
async def test_message_polling_route_handles_exceptions(
    client: TestClient,
    auth_headers: dict
):
    """Test route handler properly handles business logic exceptions."""

    with patch("src.api.routes.conversations.handle_get_message_updates") as mock_handler:
        mock_handler.side_effect = Exception("Business logic error")

        response = client.get(
            "/conversations/test-slug/messages/updates",
            headers=auth_headers
        )

        # Route should handle exception gracefully
        assert response.status_code == 500
```

#### Step 2.2: Write Business Logic Handler Tests

Create `tests/test_logic/test_message_polling_processing.py`:

```python
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

from src.logic.conversation_processing import handle_get_message_updates
from src.models.conversation import Conversation
from src.models.message import Message
from tests.shared_test_data import create_test_user, create_test_conversation


@pytest.mark.logic
@pytest.mark.messages
async def test_handle_get_message_updates_with_new_messages():
    """Test business logic handler processes new messages correctly."""

    # Mock dependencies
    mock_user = create_test_user()
    mock_conversation = create_test_conversation()
    mock_service = AsyncMock()
    mock_service.get_messages_since.return_value = [
        Message(
            id="msg-1",
            content="New message",
            created_at=datetime.now(timezone.utc),
            sender=create_test_user(username="sender")
        )
    ]

    # Act
    result = await handle_get_message_updates(
        slug="test-slug",
        if_modified_since="Wed, 21 Oct 2015 07:28:00 GMT",
        user=mock_user,
        conversation_service=mock_service
    )

    # Assert business logic
    assert result["has_updates"] is True
    assert "<li class=\"message\"" in result["html_content"]
    assert "etag" in result
    assert "last_modified" in result

    # Verify service was called correctly
    mock_service.get_messages_since.assert_called_once()

@pytest.mark.logic
@pytest.mark.messages
async def test_handle_get_message_updates_no_new_messages():
    """Test business logic handler when no new messages."""

    mock_user = create_test_user()
    mock_service = AsyncMock()
    mock_service.get_messages_since.return_value = []

    result = await handle_get_message_updates(
        slug="test-slug",
        if_modified_since="Mon, 01 Jan 2024 15:30:00 GMT",
        user=mock_user,
        conversation_service=mock_service
    )

    assert result["has_updates"] is False
    assert "etag" in result
    assert "last_modified" in result

@pytest.mark.logic
@pytest.mark.messages
async def test_handle_get_message_updates_permission_check():
    """Test business logic enforces conversation permissions."""

    mock_user = create_test_user()
    mock_service = AsyncMock()
    mock_service.get_messages_since.side_effect = PermissionError("Not authorized")

    with pytest.raises(PermissionError):
        await handle_get_message_updates(
            slug="test-slug",
            if_modified_since="Wed, 21 Oct 2015 07:28:00 GMT",
            user=mock_user,
            conversation_service=mock_service
        )
```

#### Step 2.3: Run API Tests (Should Fail)

```bash
pytest -m api tests/test_api/test_message_polling.py -v
# Expected: FAIL - route handler doesn't exist

pytest -m logic tests/test_logic/test_message_polling_processing.py -v
# Expected: FAIL - business logic handler doesn't exist
```

### **Phase 3: Implementation - Ultra-Thin Route Handler**

**Objective**: Implement the ultra-thin route handler that delegates to business logic, following the established architecture pattern.

#### Step 3.1: Add Ultra-Thin Route Handler

Add to `src/api/routes/conversations.py`:

```python
# Add imports
from fastapi import Header
from fastapi.responses import Response
from typing import Optional

@router.get(
    "/conversations/{slug}/messages/updates",
    tags=["conversations", "messages"],
)
async def get_message_updates(
    slug: str,
    request: Request,
    if_modified_since: Optional[str] = Header(None, alias="If-Modified-Since"),
    handler = Depends(handle_get_message_updates),  # Single dependency
):
    """
    Ultra-thin route handler for message polling.
    Only handles request/response format - all logic delegated to handler.
    """
    result = await handler(
        slug=slug,
        if_modified_since=if_modified_since,
        request=request
    )

    # Format response based on business logic result
    if result["has_updates"]:
        return Response(
            content=result["html_content"],
            status_code=200,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "ETag": result["etag"],
                "Last-Modified": result["last_modified"],
                "Cache-Control": "no-cache, must-revalidate"
            }
        )
    else:
        return Response(
            status_code=304,
            headers={
                "ETag": result["etag"],
                "Last-Modified": result["last_modified"],
                "Cache-Control": "no-cache, must-revalidate"
            }
        )
```

#### Step 3.2: Create Business Logic Handler

Create `src/logic/conversation_processing.py` function:

```python
# Add imports
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, formatdate
from typing import Optional, Dict, Any

from fastapi import Depends, Request, HTTPException
from jinja2 import Environment

from src.models.user import User
from src.services.conversation_service import ConversationService
from src.services.dependencies import get_conversation_service
from src.middleware.presence import current_active_user
from src.core.templating import get_jinja_env


async def handle_get_message_updates(
    slug: str,
    if_modified_since: Optional[str],
    request: Request,
    user: User = Depends(current_active_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
    jinja_env: Environment = Depends(get_jinja_env),
) -> Dict[str, Any]:
    """
    Business logic handler for message polling.
    Contains all authentication, authorization, validation, service calls.
    """
    try:
        # 1. Get conversation and verify access
        conversation = await conversation_service.get_conversation_by_slug(slug)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # 2. Verify user is participant
        if not await conversation_service.is_user_participant(conversation.id, user.id):
            raise HTTPException(status_code=403, detail="Access denied")

        # 3. Parse client's timestamp
        client_timestamp = None
        if if_modified_since:
            try:
                client_timestamp = parsedate_to_datetime(if_modified_since)
            except (ValueError, TypeError):
                # Invalid timestamp format, treat as no timestamp
                pass

        # 4. Get messages since client timestamp
        messages = await conversation_service.get_messages_since(
            conversation.id,
            since=client_timestamp
        )

        # 5. Generate ETag and Last-Modified based on latest message
        latest_message_time = conversation.last_activity_at
        if messages:
            latest_message_time = max(msg.created_at for msg in messages)

        etag = f'"{latest_message_time.isoformat()}"'
        last_modified = formatdate(latest_message_time.timestamp(), usegmt=True)

        # 6. Check if client has latest version
        if client_timestamp and client_timestamp >= latest_message_time:
            return {
                "has_updates": False,
                "etag": etag,
                "last_modified": last_modified
            }

        # 7. Render new messages as HTML fragments
        template = jinja_env.get_template("conversations/_message_list.html")
        html_content = template.render(
            messages=messages,
            current_user=user,
            request=request
        )

        return {
            "has_updates": True,
            "html_content": html_content,
            "etag": etag,
            "last_modified": last_modified
        }

    except HTTPException:
        raise
    except Exception as e:
        # Log the error in production
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### Step 3.3: Add Service Method

Add to `src/services/conversation_service.py`:

```python
async def get_messages_since(
    self,
    conversation_id: UUID,
    since: Optional[datetime] = None
) -> List[Message]:
    """Get messages from conversation since specified timestamp."""
    return await self.message_repository.get_messages_since(
        conversation_id=conversation_id,
        since=since
    )
```

Add to `src/repositories/message_repository.py`:

```python
async def get_messages_since(
    self,
    conversation_id: UUID,
    since: Optional[datetime] = None
) -> List[Message]:
    """Get messages from conversation since specified timestamp."""
    query = (
        select(Message)
        .options(selectinload(Message.sender))
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
    )

    if since:
        query = query.where(Message.created_at > since)

    result = await self.session.execute(query)
    return result.scalars().all()
```

#### Step 3.4: Create Message List Template

Create `src/templates/conversations/_message_list.html`:

```html
{% for message in messages %}
<li class="message" data-message-id="{{ message.id }}">
  <div class="message-header">
    <strong class="sender">{{ message.sender.username }}</strong>
    <span class="timestamp">{{ message.created_at.strftime('%I:%M %p') }}</span>
  </div>
  <div class="message-content">{{ message.content }}</div>
</li>
{% endfor %}
```

#### Step 3.5: Run Implementation Tests

```bash
pytest -m api tests/test_api/test_message_polling.py -v
# Expected: PASS - route handler delegates correctly

pytest -m logic tests/test_logic/test_message_polling_processing.py -v
# Expected: PASS - business logic works correctly
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

Following the "Testing the Waiter, Not the Chef" philosophy:

1. **Write failing contract tests** → Define API communication format (testing the waiter)
2. **Write failing API route tests** → Test ultra-thin route handler delegation
3. **Write failing business logic tests** → Test actual functionality (testing the chef)
4. **Implement ultra-thin route handler** → Just formats requests/responses
5. **Implement business logic handler** → Contains all authentication, validation, services
6. **Update frontend templates** → Enable htmx polling
7. **Run contract verification** → Ensure API can parse client requests
8. **Run full test suite** → Verify complete feature

## 📋 Success criteria

**Feature complete when**:

**Contract Tests**:

- ✅ htmx client sends correct request format
- ✅ API returns proper response format and headers
- ✅ Provider can parse consumer's requests

**API Tests**:

- ✅ Route handler delegates to business logic correctly
- ✅ Route handler formats responses properly
- ✅ Authentication/authorization enforced at route level

**Business Logic Tests**:

- ✅ Permissions and validation work correctly
- ✅ Service methods return expected data
- ✅ Error handling works as designed

**Integration**:

- ✅ Manual testing shows 2-3 second message latency
- ✅ No performance degradation in existing functionality
- ✅ Test coverage > 85% for new code

This TDD approach ensures:

- ✅ **Communication verified** before implementation (contract tests)
- ✅ **Clean separation** between request handling and business logic
- ✅ **Fast feedback loops** through focused, layered testing
- ✅ **Regression protection** for both API format and business logic
- ✅ **Clear boundaries** between what each layer is responsible for
