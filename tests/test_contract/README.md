# Contract Tests: Testing the Waiter, Not the Chef

This directory contains contract tests using the Pact framework to ensure API compatibility between consumers and providers. Our approach follows the "waiter vs chef" testing philosophy - **contract tests verify that systems can communicate correctly, while functional tests verify they communicate meaningfully**.

## 🎯 Core Philosophy: The Restaurant Analogy

### Testing the Waiter (Contract Tests) ✅ What We Do

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

### Testing the Chef (Functional Tests) ❌ What We Don't Do

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

## 🏗️ Architecture: Ultra-Thin Layer Approach

We separate API contract verification from business logic using a two-layer architecture:

### Layer 1: Route Handlers (Ultra-Thin)

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

### Layer 2: Business Logic Handlers (Full Logic)

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

### Contract Test Mocking Strategy

Provider tests mock **only** the business logic handler, keeping the route layer intact:

```python
# Mock configuration - only mock the business logic layer
dependency_config = {
    "app.api.routes.conversations.handle_create_conversation": {
        "return_value_config": MockDataFactory.create_conversation()
    }
}
```

## 📋 Test Responsibilities Matrix

| Test Type                       | Purpose                       | What It Verifies                     | What It Mocks                | Speed  |
| ------------------------------- | ----------------------------- | ------------------------------------ | ---------------------------- | ------ |
| **Consumer Contract**           | Client sends correct format   | Request structure, headers, encoding | Entire provider API          | Fast   |
| **Provider Contract**           | API parses requests correctly | Route handling, response format      | Business logic handlers only | Fast   |
| **Functional (Route→Handler)**  | Route delegates correctly     | Handler is called with right params  | Handler implementation       | Fast   |
| **Functional (Business Logic)** | Business rules work correctly | Authentication, validation, services | External dependencies        | Medium |
| **Integration**                 | End-to-end functionality      | Complete user workflows              | Nothing (real dependencies)  | Slow   |

## 📁 Directory Structure

```
tests/test_contract/
├── README.md                          # This file - philosophy and patterns
├── conftest.py                        # Test configuration and fixtures
├── constants.py                       # Shared test constants
├── pytest.ini                         # Pytest configuration
│
├── tests/                             # All test implementations
│   ├── consumer/                      # Consumer contract tests (client-side)
│   │   ├── test_auth_form.py         # Authentication form tests
│   │   ├── test_conversation_form.py  # Conversation creation form tests
│   │   └── test_invitation_form.py    # Invitation handling form tests
│   │
│   ├── provider/                      # Provider contract tests (API-side)
│   │   ├── test_auth_verification.py      # Auth API verification
│   │   ├── test_conversations_verification.py # Conversations API verification
│   │   └── test_participants_verification.py  # Participants API verification
│   │
│   └── shared/                        # Shared utilities and patterns
│       ├── helpers.py                 # Test helper functions
│       ├── mock_data_factory.py       # Consistent mock data creation
│       └── provider_verification_base.py # Base class for provider tests
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

## 🔧 Implementation Patterns

### Consumer Test Pattern

Consumer tests use Playwright to interact with real web forms:

```python
# tests/consumer/test_conversation_form.py
@pytest.mark.consumer
@pytest.mark.conversations
async def test_consumer_conversation_create_success(page: Page):
    """Test form submission creates correct Pact contract."""

    # Setup Pact expectation
    pact.given("user is authenticated and target user exists")
        .upon_receiving("a request to create a new conversation")
        .with_request(
            method="POST",
            path="/conversations",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="invitee_username=testuser&initial_message=Hello..."
        )
        .will_respond_with(
            status=303,
            headers={"Location": "/conversations/mock-slug"}
        )

    # Interact with real form
    with pact:
        await page.goto("/conversations/new")
        await page.locator("input[name='invitee_username']").fill("testuser")
        await page.locator("textarea[name='initial_message']").fill("Hello...")
        await page.locator("button[type='submit']").click()
```

### Provider Test Pattern

Provider tests use the `BaseProviderVerification` pattern:

```python
# tests/provider/test_conversations_verification.py
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
        """Mock only the business logic handler."""
        return MockDataFactory.create_conversation_dependency_config()

# Standard test implementation
@create_provider_test_decorator(
    conversations_verification.dependency_config,
    "with_conversations_api_mocks"
)
@pytest.mark.provider
@pytest.mark.conversations
def test_provider_conversations_pact_verification(provider_server: URL):
    """Verify API can handle consumer's request format."""
    conversations_verification.verify_pact(provider_server)
```

### Mock Data Factory Pattern

Centralized, consistent mock data creation:

```python
# tests/shared/mock_data_factory.py
class MockDataFactory:
    """Factory for creating consistent mock data across all contract tests."""

    # Standard test constants
    MOCK_USER_ID = "550e8400-e29b-41d4-a716-446655440001"
    TEST_USERNAME = "testuser"

    @classmethod
    def create_conversation_dependency_config(cls):
        """Create mock config for conversation endpoints."""
        return {
            "app.api.routes.conversations.handle_create_conversation": {
                "return_value_config": cls.create_conversation()
            }
        }

    @classmethod
    def create_conversation(cls, **overrides):
        """Create consistent conversation mock data."""
        return Conversation(
            id=overrides.get('id', str(uuid4())),
            slug=overrides.get('slug', 'mock-slug'),
            name=overrides.get('name', 'Test Conversation'),
            # ... other fields
        )
```

## 🚀 Running Tests

### Consumer Tests (Generate Pact Files)

```bash
# Run all consumer tests
pytest tests/consumer/

# Run by category
pytest tests/consumer/ -m auth
pytest tests/consumer/ -m conversations
pytest tests/consumer/ -m invitations
```

### Provider Tests (Verify Against Pact Files)

```bash
# Run all provider verification tests
pytest tests/provider/

# Run by category
pytest tests/provider/ -m auth
pytest tests/provider/ -m conversations
```

### All Contract Tests

```bash
# Run complete contract test suite
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run specific test file
pytest tests/consumer/test_conversation_form.py::test_consumer_conversation_create_success
```

## ➕ Adding New Contract Tests

### Step 1: Consumer Test

```python
# tests/consumer/test_new_feature_form.py
@pytest.mark.consumer
@pytest.mark.new_feature
async def test_consumer_new_feature_success(page: Page):
    """Test new feature form submission."""

    # Define Pact contract
    pact = setup_pact("new-feature-form", "features-api")
    pact.given("user is authenticated")
        .upon_receiving("a request to create new feature")
        .with_request(
            method="POST",
            path="/features",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="feature_name=test&description=test+description"
        )
        .will_respond_with(status=201, body={"id": "mock-id"})

    # Test form interaction
    with pact:
        await page.goto("/features/new")
        await page.fill("input[name='feature_name']", "test")
        await page.fill("textarea[name='description']", "test description")
        await page.click("button[type='submit']")
```

### Step 2: Provider Test

```python
# tests/provider/test_features_verification.py
class FeaturesVerification(BaseProviderVerification):
    @property
    def provider_name(self) -> str:
        return "features-api"

    @property
    def consumer_name(self) -> str:
        return "new-feature-form"

    @property
    def dependency_config(self):
        return MockDataFactory.create_feature_dependency_config()

@create_provider_test_decorator(
    features_verification.dependency_config,
    "with_features_api_mocks"
)
@pytest.mark.provider
@pytest.mark.new_feature
def test_provider_features_pact_verification(provider_server: URL):
    features_verification.verify_pact(provider_server)
```

### Step 3: Mock Data Factory

```python
# Add to tests/shared/mock_data_factory.py
@classmethod
def create_feature_dependency_config(cls):
    return {
        "app.api.routes.features.handle_create_feature": {
            "return_value_config": cls.create_feature()
        }
    }

@classmethod
def create_feature(cls, **overrides):
    return Feature(
        id=overrides.get('id', 'mock-feature-id'),
        name=overrides.get('name', 'Test Feature'),
        description=overrides.get('description', 'Test Description')
    )
```

## 🎯 Test Categories & Markers

```python
# Pytest markers for organizing tests
pytest.mark.consumer      # Consumer contract tests
pytest.mark.provider      # Provider contract tests
pytest.mark.auth          # Authentication-related tests
pytest.mark.conversations # Conversation-related tests
pytest.mark.invitations   # Invitation-related tests
pytest.mark.participants  # Participant-related tests
pytest.mark.slow          # Slow running tests (>5 seconds)
```

## ✅ What Contract Tests Protect Against

### Format Mismatches

```
❌ Consumer sends: {"invitee_username": "test"}  (JSON)
✅ Provider expects: invitee_username=test       (form-encoded)
→ Contract test catches this mismatch
```

### Missing Required Fields

```
❌ Consumer sends: initial_message=hello
✅ Provider expects: invitee_username=test&initial_message=hello
→ Contract test catches missing field
```

### Wrong HTTP Methods

```
❌ Consumer sends: GET /conversations
✅ Provider expects: POST /conversations
→ Contract test catches method mismatch
```

### Response Format Changes

```
❌ Provider returns: 200 OK with JSON body
✅ Consumer expects: 303 Redirect with Location header
→ Contract test catches response mismatch
```

## ❌ What Contract Tests DON'T Protect Against

### Business Logic Issues

```
✅ Contract: Request format is correct
❌ Business: Whether user actually exists
→ Functional tests handle business logic
```

### Data Validation

```
✅ Contract: Email field is present
❌ Validation: Whether email format is valid
→ Functional tests handle validation
```

### Service Integration

```
✅ Contract: API accepts request
❌ Integration: Whether database saves correctly
→ Integration tests handle service interactions
```

## 🔧 Configuration

Key configuration files:

- `conftest.py` - Test fixtures and setup
- `constants.py` - Shared test constants
- `pytest.ini` - Pytest configuration and markers
- `infrastructure/config.py` - Server and database configuration

## 🐛 Troubleshooting

### Common Issues

1. **Pact file not found**: Run consumer tests first to generate Pact files
2. **Provider verification fails**: Check mock configuration matches expected response
3. **Form submission fails**: Verify form field names match Pact request body
4. **Server startup issues**: Check port conflicts and dependency overrides

### Debug Commands

```bash
# Run with verbose output
pytest tests/ -v -s

# Run single test with debugging
pytest tests/consumer/test_conversation_form.py::test_consumer_conversation_create_success -v -s

# Check generated Pact files
cat artifacts/pacts/create-conversation-form-conversations-api.json
```

## 📚 References

- [Contract Tests Philosophy: Waiter vs Chef](./notes/contract-tests-verify-waiter-not-chef.md.md)
- [Implementation Example: POST /conversations](./notes/contract_test_example_create_conversation.md)
- [Pact Documentation](https://docs.pact.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)

---

**Remember**: Contract tests verify communication format, functional tests verify communication content. Keep them separate and focused on their specific responsibilities.
