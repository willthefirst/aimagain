# Implementation plan: Message sending feature

## 🎯 Overview

This plan implements the ability for users to send messages to conversations they have joined. The implementation follows the established TDD workflow and focuses on two testing layers: **Contract Tests** and **API Integration Tests**.

## 🏗️ TDD workflow

For each step below, the workflow is:

1. **Write Failing Test:** Add the test case using `pytest` conventions
2. **Run `pytest`:** Confirm the new test fails with expected error and other tests pass
3. **Write Minimal Code:** Implement only necessary code to make the failing test pass
4. **Run `pytest`:** Confirm new test passes and all previous tests still pass
5. **Refactor (Optional):** Improve implementation while ensuring all tests continue to pass

---

## 📋 Step-by-step implementation plan

### **Step 1: Add message form to conversation detail page**

**Goal:** Add a form to `templates/conversations/detail.html` that allows users to send messages.

#### **Red phase - Write failing test**

- **File:** `tests/test_api/test_get_conversation.py`
- **Test:** Add `test_get_conversation_has_message_form`
- **Logic:**
  - Use authenticated client to GET `/conversations/{slug}` for a conversation where user is JOINED
  - Parse HTML response with `selectolax`
  - Assert presence of `<form action="/conversations/{slug}/messages" method="post">`
  - Assert presence of `<textarea name="message_content">`
  - Assert presence of submit button

#### **Run pytest**

```bash
pytest tests/test_api/test_get_conversation.py::test_get_conversation_has_message_form -v
```

Expected: Test fails (form elements not found)

#### **Green phase - Write code**

- **File:** `templates/conversations/detail.html`
- **Changes:** Add message form after the messages list:

```html
<hr />
<h2>Send a message</h2>
<form
  action="{{ url_for('create_message', slug=conversation.slug) }}"
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
  <button type="submit">Send Message</button>
</form>
```

#### **Run pytest**

```bash
pytest tests/test_api/test_get_conversation.py::test_get_conversation_has_message_form -v
```

Expected: Test passes

---

### **Step 2: Create message creation route**

**Goal:** Implement `POST /conversations/{slug}/messages` endpoint.

#### **Red phase - Write failing test**

- **File:** `tests/test_api/test_create_message.py` (new file)
- **Test:** `test_create_message_success`
- **Logic:**
  - Setup: Create conversation with authenticated user as JOINED participant
  - Send POST to `/conversations/{slug}/messages` with form data `{"message_content": "Test message"}`
  - Assert: 303 redirect to `/conversations/{slug}`
  - Assert: Message created in database with correct content and sender
  - Assert: Conversation `last_activity_at` updated

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py::test_create_message_success -v
```

Expected: Test fails (404 - route doesn't exist)

#### **Green phase - Write code**

- **File:** `app/api/routes/conversations.py`
- **Changes:** Add new route:

```python
@router.post(
    "/conversations/{slug}/messages",
    status_code=status.HTTP_303_SEE_OTHER,
    name="create_message",
    tags=["conversations", "messages"],
)
async def create_message(
    slug: str,
    message_content: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Handles creating a new message in a conversation."""
    # Minimal implementation to pass test
    # TODO: Add proper logic in next steps
    redirect_url = f"/conversations/{slug}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
```

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py::test_create_message_success -v
```

Expected: Test fails (message not created in database)

---

### **Step 3: Implement service layer message creation**

**Goal:** Add message creation logic to `ConversationService`.

#### **Red phase - Write additional tests**

- **File:** `tests/test_api/test_create_message.py`
- **Tests:** Add authorization and validation tests:
  - `test_create_message_conversation_not_found` (403)
  - `test_create_message_not_participant` (403)
  - `test_create_message_invited_status` (403)
  - `test_create_message_empty_content` (400)

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py -v
```

Expected: All new tests fail

#### **Green phase - Write code**

- **File:** `app/services/conversation_service.py`
- **Changes:** Add `create_message_in_conversation` method:

```python
async def create_message_in_conversation(
    self,
    conversation_slug: str,
    message_content: str,
    sender_user: User,
) -> Message:
    """Creates a new message in an existing conversation."""
    # Validate conversation exists
    conversation = await self.conv_repo.get_conversation_by_slug(conversation_slug)
    if not conversation:
        raise ConversationNotFoundError(f"Conversation with slug '{conversation_slug}' not found.")

    # Check authorization
    participant = await self.part_repo.get_participant_by_user_and_conversation(
        user_id=sender_user.id, conversation_id=conversation.id
    )
    if not participant:
        raise NotAuthorizedError("User is not a participant in this conversation.")

    if participant.status != ParticipantStatus.JOINED:
        raise NotAuthorizedError("Only joined participants can create messages.")

    # Validate content
    if not message_content or not message_content.strip():
        raise BusinessRuleError("Message content cannot be empty.")

    try:
        # Create message
        new_message = await self.msg_repo.create_message(
            content=message_content.strip(),
            conversation_id=conversation.id,
            user_id=sender_user.id,
        )

        # Update conversation timestamp
        await self.conv_repo.update_conversation_timestamps(conversation)

        # Commit transaction
        await self.session.commit()
        await self.session.refresh(new_message)

        return new_message

    except IntegrityError as e:
        await self.session.rollback()
        logger.warning(f"Integrity error creating message: {e}", exc_info=True)
        raise ConflictError("Could not create message due to a data conflict.")
    except SQLAlchemyError as e:
        await self.session.rollback()
        logger.error(f"Database error creating message: {e}", exc_info=True)
        raise DatabaseError("Failed to create message due to a database error.")
    except Exception as e:
        await self.session.rollback()
        logger.error(f"Unexpected error creating message: {e}", exc_info=True)
        raise ServiceError("An unexpected error occurred while creating the message.")
```

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py -v
```

Expected: Tests still fail (route doesn't call service)

---

### **Step 4: Connect route to service layer**

**Goal:** Update the route to call the service and handle errors properly.

#### **Green phase - Write code**

- **File:** `app/api/routes/conversations.py`
- **Changes:** Update `create_message` route:

```python
async def create_message(
    slug: str,
    message_content: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Handles creating a new message in a conversation."""
    logger.info(f"Creating message in conversation {slug} by user {user.id}")

    try:
        await conv_service.create_message_in_conversation(
            conversation_slug=slug,
            message_content=message_content,
            sender_user=user,
        )

        # Redirect back to conversation detail page
        redirect_url = f"/conversations/{slug}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    except (ConversationNotFoundError, NotAuthorizedError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (BusinessRuleError, ConflictError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (DatabaseError, ServiceError) as e:
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py -v
```

Expected: All tests pass

---

### **Step 5: Refactor with processing handler**

**Goal:** Extract business logic into a processing handler for better separation of concerns.

#### **Refactor phase - Create handler**

- **File:** `app/logic/conversation_processing.py`
- **Changes:** Add `handle_create_message` function:

```python
async def handle_create_message(
    conversation_slug: str,
    message_content: str,
    sender_user: User,
    conv_service: ConversationService,
) -> Message:
    """Handles the core logic for creating a message in a conversation."""
    try:
        new_message = await conv_service.create_message_in_conversation(
            conversation_slug=conversation_slug,
            message_content=message_content,
            sender_user=sender_user,
        )

        logger.info(f"Message created by user {sender_user.id} in conversation {conversation_slug}")
        return new_message

    except (ConversationNotFoundError, NotAuthorizedError, BusinessRuleError,
            ConflictError, DatabaseError, ServiceError) as e:
        logger.info(f"Service error creating message: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error in handle_create_message: {e}", exc_info=True)
        raise ServiceError("An unexpected error occurred while creating the message.")
```

#### **Refactor phase - Update route**

- **File:** `app/api/routes/conversations.py`
- **Changes:** Simplify route to use handler:

```python
async def create_message(
    slug: str,
    message_content: str = Form(...),
    user: User = Depends(current_active_user),
    conv_service: ConversationService = Depends(get_conversation_service),
):
    """Handles creating a new message in a conversation."""
    try:
        await handle_create_message(
            conversation_slug=slug,
            message_content=message_content,
            sender_user=user,
            conv_service=conv_service,
        )

        redirect_url = f"/conversations/{slug}"
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    except (ConversationNotFoundError, NotAuthorizedError) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (BusinessRuleError, ConflictError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (DatabaseError, ServiceError) as e:
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### **Run pytest**

```bash
pytest tests/test_api/test_create_message.py -v
```

Expected: All tests still pass (refactoring doesn't change behavior)

---

### **Step 6: Contract tests - Consumer**

**Goal:** Create consumer contract tests for message creation form interaction.

#### **Write consumer test**

- **File:** `tests/test_contract/tests/consumer/test_message_form.py` (new file)
- **Test:** `test_consumer_create_message_success`
- **Logic:**
  - Setup Pact expectation for POST `/conversations/{slug}/messages`
  - Use Playwright to interact with message form
  - Fill textarea and submit form
  - Verify Pact contract is satisfied

```python
@pytest.mark.consumer
@pytest.mark.messages
async def test_consumer_create_message_success(page: Page):
    """Test message form submission creates correct Pact contract."""

    pact = setup_pact("create-message-form", "conversations-api")
    pact.given("user is joined participant in conversation")
        .upon_receiving("a request to create a message")
        .with_request(
            method="POST",
            path=matchers.like("/conversations/test-slug/messages"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="message_content=Hello+world"
        )
        .will_respond_with(
            status=303,
            headers={"Location": matchers.like("/conversations/test-slug")}
        )

    with pact:
        await page.goto("/conversations/test-slug")
        await page.locator("textarea[name='message_content']").fill("Hello world")
        await page.locator("button[type='submit']").click()
```

#### **Run consumer test**

```bash
# Run consumer test (generates Pact file)
pytest tests/test_contract/tests/consumer/test_message_form.py -v
```

---

### **Step 7: Contract tests - Provider**

**Goal:** Create provider verification tests for message creation API.

#### **Red phase - Write provider test**

- **File:** `tests/test_contract/tests/provider/test_messages_verification.py` (new file)
- **Test:** `test_provider_messages_pact_verification`

#### **Green phase - Setup mock data factory**

- **File:** `tests/test_contract/tests/shared/mock_data_factory.py`
- **Changes:** Add message-related mock methods:

```python
@classmethod
def create_message_dependency_config(cls):
    return {
        "app.logic.conversation_processing.handle_create_message": {
            "return_value_config": cls.create_message()
        }
    }

@classmethod
def create_message(cls, **overrides):
    return Message(
        id=overrides.get('id', cls.MOCK_MESSAGE_ID),
        content=overrides.get('content', 'Test message'),
        conversation_id=overrides.get('conversation_id', cls.MOCK_CONVERSATION_ID),
        created_by_user_id=overrides.get('created_by_user_id', cls.MOCK_USER_ID),
        created_at=overrides.get('created_at', datetime.now(timezone.utc))
    )
```

#### **Green phase - Write provider verification**

```python
class MessagesVerification(BaseProviderVerification):
    @property
    def provider_name(self) -> str:
        return "conversations-api"

    @property
    def consumer_name(self) -> str:
        return "create-message-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_message_dependency_config()

@create_provider_test_decorator(
    messages_verification.dependency_config,
    "with_messages_api_mocks"
)
@pytest.mark.provider
@pytest.mark.messages
def test_provider_messages_pact_verification(provider_server: URL):
    messages_verification.verify_pact(provider_server)
```

#### **Run provider test**

```bash
pytest tests/test_contract/tests/provider/test_messages_verification.py -v
```

Expected: Test passes (verifies API can handle consumer's request format)

---

## 🧪 Complete test suite

### **Run all tests**

```bash
# Run all tests to ensure no regressions
pytest

# Run specific test categories
pytest -m messages                    # All message-related tests
pytest tests/test_api/test_create_message.py  # API integration tests
pytest tests/test_contract/ -m messages     # Contract tests only
```

### **Test coverage summary**

| Test Type             | File                            | Purpose                                   |
| --------------------- | ------------------------------- | ----------------------------------------- |
| **API Integration**   | `test_create_message.py`        | End-to-end message creation functionality |
| **API Integration**   | `test_get_conversation.py`      | Message form presence in UI               |
| **Contract Consumer** | `test_message_form.py`          | Form submission format verification       |
| **Contract Provider** | `test_messages_verification.py` | API request handling verification         |

---

## ✅ Success criteria

After completing all steps:

1. **Functionality:** Users can create messages in conversations they've joined
2. **Authorization:** Only joined participants can create messages
3. **Validation:** Empty messages are rejected
4. **UI:** Message form appears on conversation detail page
5. **API:** Proper HTTP responses and redirects
6. **Database:** Messages are persisted and conversation timestamps updated
7. **Tests:** All existing tests pass + new comprehensive test coverage
8. **Contracts:** API format compatibility verified

This implementation follows the established TDD workflow and maintains the two-layer testing approach (Contract + API) as requested.
