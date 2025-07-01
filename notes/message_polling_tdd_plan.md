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

### **Phase 1: Contract Tests - API Communication Format**

**Objective**: Ensure the polling endpoint has the correct request/response format for htmx integration.

#### Step 1.1: Write Failing Contract Tests

Create `tests/test_contract/tests/consumer/test_message_polling.py`:

```python
@pytest.mark.contract
async def test_message_polling_endpoint_contract(page: Page):
    """Contract test: htmx client can poll for message updates."""
    await setup_pact_interaction(
        pact.given("user authenticated and conversation exists with messages")
        .upon_receiving("message polling request")
        .with_request(
            method="GET",
            path="/conversations/test-slug/messages/updates",
            headers={
                "Accept": "text/html",
                "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"
            }
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body="<li class=\"message\">New message content</li>"
        )
    )

    # Simulate htmx polling request
    await page.goto("/conversations/test-slug")

    # Verify the endpoint gets called correctly
    await expect_pact_request_made()

@pytest.mark.contract
async def test_message_polling_no_updates_contract(page: Page):
    """Contract test: 304 Not Modified when no new messages."""
    await setup_pact_interaction(
        pact.given("user authenticated and no new messages")
        .upon_receiving("message polling request with current timestamp")
        .with_request(
            method="GET",
            path="/conversations/test-slug/messages/updates",
            headers={"If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT"}
        )
        .will_respond_with(status=304)  # No body for 304
    )
```

Create `tests/test_contract/tests/provider/test_message_polling_verification.py`:

```python
@pytest.mark.contract
def test_message_polling_provider_contract(provider_server):
    """Provider verification: API correctly handles polling requests."""
    verification.verify_pact(
        provider_server,
        pact_file="message_polling_consumer-conversations_provider.json"
    )
```

#### Step 1.2: Run Contract Tests (Should Fail)

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
