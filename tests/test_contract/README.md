# Contract tests: Testing the waiter, not the chef

This directory contains contract tests using the Pact framework to ensure API compatibility between consumers and providers. Our approach follows the "waiter vs chef" testing philosophy - **contract tests verify that systems can communicate correctly, while functional tests verify they communicate meaningfully**.

## 🎯 Core philosophy: The restaurant analogy

### Testing the waiter (contract tests) ✅ what we do

- **Request Format Validation**: Verifies client sends data in correct format (`application/x-www-form-urlencoded` vs `application/json`)
- **Required Fields**: Ensures all mandatory fields are present (`invitee_username`, `initial_message`)
- **Protocol Compliance**: Confirms proper HTTP methods, headers, and response codes
- **Message Structure**: Validates request/response structure matches API specification

**Example**: For `POST /conversations` with form data:

```
✅ Verifies: Content-Type header is application/x-www-form-urlencoded
✅ Verifies: Body contains invitee_username and initial_message fields
✅ Verifies: Response is 303 redirect with Location header
✅ Verifies: API can parse the request without errors
```

### Testing the chef (functional tests) ❌ what we don't do

- **Business Logic**: Whether user exists, permissions, validation rules
- **Data Processing**: How data is transformed, stored, or retrieved
- **Service Integration**: Database operations, external API calls
- **Error Handling**: Business-specific error conditions and responses

**Example**: For `POST /conversations`:

```
❌ Don't Test: Whether invitee_username corresponds to real user
❌ Don't Test: Whether conversation is actually created in database
❌ Don't Test: Whether user has permission to create conversations
❌ Don't Test: Complex validation logic or business rules
```

## 🏗️ Architecture: Ultra-thin layer approach

We separate API contract verification from business logic using a two-layer architecture:

### Layer 1: Route handlers (Ultra-thin)

```python
@router.post("/conversations", response_model=ConversationResponse)
async def conversation_request_handler(
    request_data: ConversationCreateRequest,  # FastAPI validates schema
    handler = Depends(handle_create_conversation),  # Single dependency
    request: Request
):
    """Ultra-thin - only handles request/response format."""
    return await handler(request_data=request_data, request=request)
```

**Responsibilities**: Request parsing, response formatting, dependency injection

### Layer 2: Business logic handlers (Full logic)

```python
async def handle_create_conversation(
    request_data: ConversationCreateRequest,
    request: Request,
    user: User = Depends(current_active_user),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    """Contains all business logic, validation, service calls."""
    # Authentication, authorization, validation, service calls, error handling
```

**Responsibilities**: Business logic, validation, service integration, error handling

### Contract test mocking strategy

Provider tests mock **only** the business logic handler, keeping the route layer intact:

```python
# Mock configuration - only mock the business logic layer
dependency_config = {
    "src.api.routes.conversations.handle_create_conversation": {
        "return_value_config": MockDataFactory.create_conversation()
    }
}
```

## 📋 Test responsibilities matrix

| Test Type                       | Purpose                       | What It Verifies                     | What It Mocks                | Speed  |
| ------------------------------- | ----------------------------- | ------------------------------------ | ---------------------------- | ------ |
| **Consumer Contract**           | Client sends correct format   | Request structure, headers, encoding | Entire provider API          | Fast   |
| **Provider Contract**           | API parses requests correctly | Route handling, response format      | Business logic handlers only | Fast   |
| **Functional (Route→Handler)**  | Route delegates correctly     | Handler is called with right params  | Handler implementation       | Fast   |
| **Functional (Business Logic)** | Business rules work correctly | Authentication, validation, services | External dependencies        | Medium |
| **Integration**                 | End-to-end functionality      | Complete user workflows              | Nothing (real dependencies)  | Slow   |

## 📁 Directory structure

```
tests/test_contract/
├── README.md                          # This file - philosophy and patterns
├── conftest.py                        # Test configuration and fixtures
├── constants.py                       # Shared test constants
├── pytest.ini                         # Pytest configuration
│
├── tests/                             # All test implementations
│   ├── consumer/                      # Consumer contract tests (client-side)
│   │   ├── pytest.ini                # Consumer-specific pytest config
│   │   ├── test_auth_form.py         # Authentication form tests
│   │   ├── test_conversation_form.py  # Conversation creation form tests
│   │   ├── test_invitation_form.py    # Invitation handling form tests
│   │   └── test_message_form.py       # Message sending form tests
│   │
│   ├── provider/                      # Provider contract tests (API-side)
│   │   ├── test_auth_verification.py      # Auth API verification
│   │   ├── test_conversations_verification.py # Conversations API verification
│   │   └── test_participants_verification.py  # Participants API verification
│   │
│   └── shared/                        # Shared utilities and patterns
│       ├── consumer_test_base.py      # Base class for consumer tests
│       ├── provider_verification_base.py # Base class for provider tests
│       ├── helpers.py                 # Test helper functions
│       └── mock_data_factory.py       # Consistent mock data creation
│
├── infrastructure/                    # Test infrastructure
│   ├── config.py                     # Configuration management
│   ├── servers/                      # Server management
│   │   ├── base.py                   # Base server functionality
│   │   ├── consumer.py               # Consumer server setup
│   │   └── provider.py               # Provider server setup
│   └── utilities/                    # Test utilities
│       └── mocks.py                  # Mocking utilities
│
└── artifacts/                        # Generated files (gitignored)
    ├── pacts/                        # Generated Pact contract files
    ├── logs/                         # Test execution logs
    └── reports/                      # Test reports
```

## 🔧 Implementation patterns

### Consumer test pattern

Consumer tests use Playwright to interact with real web forms, using constants and helpers:

```python
# tests/consumer/test_conversation_form.py
import pytest
from playwright.async_api import Page

from tests.shared_test_data import (
    TEST_INITIAL_MESSAGE,
    TEST_INVITEE_USERNAME,
    get_form_encoded_creation_data,
)
from tests.test_contract.constants import (
    CONSUMER_NAME_CONVERSATION,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_CONVERSATION,
    PROVIDER_NAME_CONVERSATIONS,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

# Test constants
CONVERSATIONS_NEW_PATH = "/conversations/new"
CONVERSATIONS_CREATE_PATH = "/conversations"
MOCK_CONVERSATION_SLUG = "mock-slug"
PROVIDER_STATE_USER_ONLINE = "user is authenticated and target user exists and is online"

@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_conversation_create_success(
    origin_with_routes: str, page: Page
):
    """Test form submission creates correct Pact contract."""
    origin = origin_with_routes

    # Setup Pact using helper function
    pact = setup_pact(
        CONSUMER_NAME_CONVERSATION,
        PROVIDER_NAME_CONVERSATIONS,
        port=PACT_PORT_CONVERSATION,
    )
    mock_server_uri = pact.uri
    new_conversation_url = f"{origin}{CONVERSATIONS_NEW_PATH}"
    mock_submit_url = f"{mock_server_uri}{CONVERSATIONS_CREATE_PATH}"

    # Use shared data functions
    expected_request_body = get_form_encoded_creation_data()
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Define Pact expectation using constants
    (
        pact.given(PROVIDER_STATE_USER_ONLINE)
        .upon_receiving("a request to create a new conversation with valid username")
        .with_request(
            method="POST",
            path=CONVERSATIONS_CREATE_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=303,
            headers={"Location": f"/conversations/{MOCK_CONVERSATION_SLUG}"}
        )
    )

    # Setup interception using helper
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=CONVERSATIONS_CREATE_PATH,
        mock_pact_url=mock_submit_url,
        http_method="POST",
    )

    # Interact with real form using constants
    with pact:
        await page.goto(new_conversation_url)
        await page.locator("input[name='invitee_username']").fill(TEST_INVITEE_USERNAME)
        await page.locator("textarea[name='initial_message']").fill(TEST_INITIAL_MESSAGE)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
```

### Provider test pattern

Provider tests use the `BaseProviderVerification` pattern with the decorator:

```python
# tests/provider/test_conversations_verification.py
import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)

class ConversationsVerification(BaseProviderVerification):
    """Conversations provider verification following standard pattern."""

    @property
    def provider_name(self) -> str:
        return "conversations-api"

    @property
    def consumer_name(self) -> str:
        return "create-conversation-form"

    @property
    def dependency_config(self):
        """Mock only the business logic handler using factory."""
        # Combine multiple configs if needed
        create_config = MockDataFactory.create_conversation_dependency_config()
        get_config = {
            "src.api.routes.conversations.handle_get_conversation": {
                "return_value_config": MockDataFactory.create_conversation(
                    name="mock-name"
                )
            }
        }
        return {**create_config, **get_config}

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.conversations]

# Create instance for use in tests
conversations_verification = ConversationsVerification()

# Standard test implementation using decorator
@create_provider_test_decorator(
    conversations_verification.dependency_config,
    "with_conversations_api_mocks"
)
def test_provider_conversations_pact_verification(provider_server: URL):
    """Verify API can handle consumer's request format."""
    conversations_verification.verify_pact(provider_server)
```

### Mock data factory pattern

Centralized, consistent mock data creation with proper constants:

```python
# tests/shared/mock_data_factory.py
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from src.models.conversation import Conversation
from src.schemas.participant import ParticipantStatus
from src.schemas.user import UserRead

class MockDataFactory:
    """Factory for creating consistent mock data across all contract tests."""

    # Standard test IDs for consistency - these are used across all tests
    MOCK_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
    MOCK_CONVERSATION_ID = "550e8400-e29b-41d4-a716-446655440002"
    MOCK_PARTICIPANT_ID = "550e8400-e29b-41d4-a716-446655440000"
    MOCK_INVITER_ID = "550e8400-e29b-41d4-a716-446655440003"
    MOCK_MESSAGE_ID = "550e8400-e29b-41d4-a716-446655440004"

    # Standard test data
    TEST_EMAIL = "test.user@example.com"
    TEST_USERNAME = "testuser"
    TEST_PASSWORD = "securepassword123"
    TEST_CONVERSATION_SLUG = "mock-slug"
    TEST_CONVERSATION_NAME = "mock-name"

    @classmethod
    def create_conversation_dependency_config(cls) -> Dict[str, Any]:
        """Create mock config for conversation endpoints."""
        return {
            "src.api.routes.conversations.handle_create_conversation": {
                "return_value_config": cls.create_conversation()
            }
        }

    @classmethod
    def create_conversation(cls, **overrides) -> Conversation:
        """Create consistent conversation mock data."""
        return Conversation(
            id=overrides.get('id', str(uuid4())),
            slug=overrides.get('slug', cls.TEST_CONVERSATION_SLUG),
            name=overrides.get('name', cls.TEST_CONVERSATION_NAME),
            created_by_user_id=overrides.get('created_by_user_id', str(uuid4())),
            last_activity_at=overrides.get(
                'last_activity_at',
                datetime.now(timezone.utc).isoformat()
            ),
        )

    @classmethod
    def create_user_read(cls, **overrides) -> UserRead:
        """Create a UserRead instance with default or provided values."""
        return UserRead(
            id=overrides.get('id', str(uuid4())),
            email=overrides.get('email', cls.TEST_EMAIL),
            username=overrides.get('username', cls.TEST_USERNAME),
            is_active=overrides.get('is_active', True),
            is_superuser=overrides.get('is_superuser', False),
            is_verified=overrides.get('is_verified', False),
        )

    @classmethod
    def create_participant_dependency_config(cls) -> Dict[str, Any]:
        """Create dependency config for participant endpoints."""
        return {
            "src.api.routes.participants.handle_update_participant_status": {
                "return_value_config": cls.create_participant()
            }
        }

    @classmethod
    def create_participant(cls, **overrides):
        """Create consistent participant mock data."""
        default_datetime = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        return Participant(
            id=overrides.get('id', cls.MOCK_PARTICIPANT_ID),
            user_id=overrides.get('user_id', cls.MOCK_USER_ID),
            conversation_id=overrides.get('conversation_id', cls.MOCK_CONVERSATION_ID),
            status=overrides.get('status', ParticipantStatus.REJECTED),
            invited_by_user_id=overrides.get('invited_by_user_id', cls.MOCK_INVITER_ID),
            initial_message_id=overrides.get('initial_message_id', cls.MOCK_MESSAGE_ID),
            created_at=overrides.get('created_at', default_datetime),
            updated_at=overrides.get('updated_at', default_datetime),
            joined_at=overrides.get('joined_at', None),
        )
```

## 🚀 Running tests

### Consumer tests (generate Pact files)

```bash
# Run all consumer tests
pytest tests/consumer/

# Run by category using pytest marks
pytest tests/consumer/ -m auth
pytest tests/consumer/ -m conversations
pytest tests/consumer/ -m invitations
pytest tests/consumer/ -m messages

# Run specific test file
pytest tests/consumer/test_conversation_form.py::test_consumer_conversation_create_success -v
```

### Provider tests (verify against Pact files)

```bash
# Run all provider verification tests
pytest tests/provider/

# Run by category
pytest tests/provider/ -m auth
pytest tests/provider/ -m conversations

# Run with verbose output
pytest tests/provider/ -v
```

### All contract tests

```bash
# Run complete contract test suite
pytest tests/

# Run with verbose output and show slow tests
pytest tests/ -v --durations=10

# Run specific test patterns
pytest tests/ -k "conversation"
```

## ➕ Adding new contract tests

### Step 1: Add constants

Add to `tests/test_contract/constants.py`:

```python
# New feature constants
TEST_FEATURE_NAME = "test-feature"
CONSUMER_NAME_FEATURE = "feature-form"
PROVIDER_NAME_FEATURES = "features-api"
PACT_PORT_FEATURES = 1240
FEATURES_PATH = "/features"
```

### Step 2: Consumer test

```python
# tests/consumer/test_feature_form.py
import pytest
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_FEATURE,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_FEATURES,
    PROVIDER_NAME_FEATURES,
    TEST_FEATURE_NAME,
    FEATURES_PATH,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

PROVIDER_STATE_USER_AUTHENTICATED = "user is authenticated"

@pytest.mark.parametrize(
    "origin_with_routes", [{"features": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_feature_create_success(
    origin_with_routes: str, page: Page
):
    """Test new feature form submission."""
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_FEATURE,
        PROVIDER_NAME_FEATURES,
        port=PACT_PORT_FEATURES,
    )
    mock_server_uri = pact.uri
    feature_form_url = f"{origin}/features/new"
    mock_submit_url = f"{mock_server_uri}{FEATURES_PATH}"

    expected_request_body = f"feature_name={TEST_FEATURE_NAME}&description=test+description"
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

    (
        pact.given(PROVIDER_STATE_USER_AUTHENTICATED)
        .upon_receiving("a request to create new feature")
        .with_request(
            method="POST",
            path=FEATURES_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            body={"id": "mock-feature-id"}
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=FEATURES_PATH,
        mock_pact_url=mock_submit_url,
        http_method="POST",
    )

    with pact:
        await page.goto(feature_form_url)
        await page.fill("input[name='feature_name']", TEST_FEATURE_NAME)
        await page.fill("textarea[name='description']", "test description")
        await page.click("button[type='submit']")
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
```

### Step 3: Provider test

```python
# tests/provider/test_features_verification.py
import pytest
from yarl import URL

from tests.test_contract.tests.shared.mock_data_factory import MockDataFactory
from tests.test_contract.tests.shared.provider_verification_base import (
    BaseProviderVerification,
    create_provider_test_decorator,
)

class FeaturesVerification(BaseProviderVerification):
    @property
    def provider_name(self) -> str:
        return "features-api"

    @property
    def consumer_name(self) -> str:
        return "feature-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_feature_dependency_config()

    @property
    def pytest_marks(self) -> list:
        return [pytest.mark.provider, pytest.mark.features]

features_verification = FeaturesVerification()

@create_provider_test_decorator(
    features_verification.dependency_config,
    "with_features_api_mocks"
)
def test_provider_features_pact_verification(provider_server: URL):
    features_verification.verify_pact(provider_server)
```

### Step 4: Mock data factory

Add to `tests/shared/mock_data_factory.py`:

```python
@classmethod
def create_feature_dependency_config(cls) -> Dict[str, Any]:
    """Create dependency config for feature endpoints."""
    return {
        "src.api.routes.features.handle_create_feature": {
            "return_value_config": cls.create_feature()
        }
    }

@classmethod
def create_feature(cls, **overrides):
    """Create consistent feature mock data."""
    return Feature(
        id=overrides.get('id', 'mock-feature-id'),
        name=overrides.get('name', 'Test Feature'),
        description=overrides.get('description', 'Test Description')
    )
```

## 🎯 Test categories & markers

Test markers are defined in `tests/consumer/pytest.ini`:

```python
pytest.mark.consumer      # Consumer contract tests
pytest.mark.provider      # Provider contract tests
pytest.mark.auth          # Authentication-related tests
pytest.mark.conversations # Conversation-related tests
pytest.mark.invitations   # Invitation-related tests
pytest.mark.participants  # Participant-related tests
pytest.mark.messages      # Message-related tests
pytest.mark.slow          # Slow running tests (>5 seconds)
```

## ✅ What contract tests protect against

### Format mismatches

```
❌ Consumer sends: {"invitee_username": "test"}  (JSON)
✅ Provider expects: invitee_username=test       (form-encoded)
→ Contract test catches this mismatch
```

### Missing required fields

```
❌ Consumer sends: initial_message=hello
✅ Provider expects: invitee_username=test&initial_message=hello
→ Contract test catches missing field
```

### Wrong HTTP methods

```
❌ Consumer sends: GET /conversations
✅ Provider expects: POST /conversations
→ Contract test catches method mismatch
```

### Response format changes

```
❌ Provider returns: 200 OK with JSON body
✅ Consumer expects: 303 Redirect with Location header
→ Contract test catches response mismatch
```

## ❌ What contract tests DON'T protect against

### Business logic issues

```
✅ Contract: Request format is correct
❌ Business: Whether user actually exists
→ Functional tests handle business logic
```

### Data validation

```
✅ Contract: Email field is present
❌ Validation: Whether email format is valid
→ Functional tests handle validation
```

### Service integration

```
✅ Contract: API accepts request
❌ Integration: Whether database saves correctly
→ Integration tests handle service interactions
```

## 🔧 Configuration

Key configuration files and their purposes:

- `conftest.py` - Test fixtures and setup with origin_with_routes parametrization
- `constants.py` - Shared test constants (ports, names, paths, test data)
- `tests/consumer/pytest.ini` - Consumer-specific pytest configuration and asyncio settings
- `infrastructure/config.py` - Server and database configuration
- `tests/shared/helpers.py` - Pact setup and Playwright interception utilities

## 🐛 Troubleshooting

### Common issues

1. **Pact file not found**: Run consumer tests first to generate Pact files

   ```bash
   pytest tests/consumer/test_conversation_form.py -v
   ```

2. **Provider verification fails**: Check mock configuration matches expected response

   ```bash
   # Check the generated pact file
   cat artifacts/pacts/create-conversation-form-conversations-api.json
   ```

3. **Form submission fails**: Verify form field names match Pact request body in constants
4. **Server startup issues**: Check port conflicts in constants.py (PACT*PORT*\* values)
5. **Asyncio loop errors**: Ensure `@pytest.mark.asyncio(loop_scope="session")` is used

### Debug commands

```bash
# Run with verbose output and show setup/teardown
pytest tests/consumer/ -v -s --setup-show

# Run single test with debugging
pytest tests/consumer/test_conversation_form.py::test_consumer_conversation_create_success -v -s

# Check generated Pact files
find artifacts/pacts/ -name "*.json" -exec cat {} \;

# Run with timeout debugging
pytest tests/consumer/ -v --timeout=300
```

### Checking constants usage

```bash
# Verify constants are being used consistently
grep -r "CONSUMER_NAME_" tests/test_contract/tests/
grep -r "MOCK_" tests/test_contract/tests/shared/mock_data_factory.py
```

## 📚 References

- [Contract Tests Philosophy: Waiter vs Chef](./notes/contract-tests-verify-waiter-not-chef.md.md)
- [Implementation Example: POST /conversations](./notes/contract_test_example_create_conversation.md)
- [Pact Documentation](https://docs.pact.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)

---

**Remember**: Contract tests verify communication format, functional tests verify communication content. Keep them separate and focused on their specific responsibilities. Always use constants from `constants.py` and the `MockDataFactory` for consistency across all tests.
