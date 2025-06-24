# Tests: Multi-layered testing strategy

The `tests/` directory contains a **comprehensive testing strategy** for the Aimagain application, implementing both contract tests for API compatibility and functional tests for business logic, organized to provide fast feedback and reliable CI/CD pipelines.

## 🎯 Core philosophy: Layered testing pyramid

Our testing approach follows a **pyramid structure** with fast, focused unit tests at the base, integration tests in the middle, and contract tests ensuring system compatibility at the API boundaries.

### What we do ✅

- **Contract testing**: Pact-based tests ensuring API consumers and providers can communicate correctly
- **Functional API testing**: FastAPI test client tests verifying business logic and workflows
- **Integration testing**: End-to-end tests with real database and external dependencies
- **Isolated testing**: MockRepository pattern for testing business logic without database
- **Performance-focused**: Fast test execution through proper mocking and test data management

**Example**: Test pyramid implementation:

```python
# Fast unit tests - mock everything external
@pytest.mark.unit
async def test_conversation_service_create_with_mocks(mock_conversation_repo):
    service = ConversationService(mock_conversation_repo)
    result = await service.create_conversation(data)
    assert result.slug.startswith("convo-")

# Integration tests - real database
@pytest.mark.integration
async def test_create_conversation_end_to_end(client, test_db):
    response = await client.post("/conversations", data=form_data)
    assert response.status_code == 303
    # Verify in database
    conversation = await test_db.get_conversation_by_slug(slug)
    assert conversation is not None
```

### What we don't do ❌

- **Flaky tests**: Tests that fail intermittently due to race conditions or timing issues
- **Slow test feedback**: All tests under 30 seconds, contract tests under 5 seconds
- **Test data pollution**: Each test is isolated with clean test data
- **Testing implementation details**: Focus on behavior and outcomes, not internal structure

**Example**: Don't test internal implementation:

```python
# ❌ Wrong - testing implementation details
def test_service_calls_repo_create_method(mock_repo):
    service.create_conversation(data)
    mock_repo.create.assert_called_once()  # Implementation detail

# ✅ Correct - testing behavior and outcomes
def test_service_creates_conversation_with_correct_data():
    result = await service.create_conversation(data)
    assert result.creator_id == data.creator_id
    assert result.status == ConversationStatus.ACTIVE
```

## 🏗️ Architecture: Test pyramid with clear boundaries

**Contract Tests → API Tests → Service Tests → Repository Tests**

Each layer has specific responsibilities and runs at different speeds.

## 📋 Test layer responsibility matrix

| Test Layer      | Speed  | Purpose           | What It Tests                                   | Dependencies      | Markers                    |
| --------------- | ------ | ----------------- | ----------------------------------------------- | ----------------- | -------------------------- |
| **Contract**    | Fast   | API compatibility | Request/response format, protocol compliance    | Mock providers    | `@pytest.mark.contract`    |
| **API**         | Medium | HTTP endpoints    | Route handling, authentication, validation      | Test database     | `@pytest.mark.api`         |
| **Service**     | Fast   | Business logic    | Service methods, business rules, error handling | Mock repositories | `@pytest.mark.service`     |
| **Repository**  | Medium | Data access       | Database queries, relationships, transactions   | Test database     | `@pytest.mark.repository`  |
| **Integration** | Slow   | End-to-end        | Complete user workflows                         | Real dependencies | `@pytest.mark.integration` |

## 📁 Directory structure

**Core test directories:**

- `test_contract/` - Pact-based contract testing for API compatibility
  - `tests/consumer/` - Consumer-side contract tests (forms, client interactions)
  - `tests/provider/` - Provider-side contract tests (API verification)
  - `infrastructure/` - Contract testing utilities and mocking

**Functional test directories:**

- `test_api/` - FastAPI route testing with business logic verification
  - Integration tests for each API endpoint
  - Authentication and authorization testing
  - Form handling and validation testing

**Supporting files:**

- `shared_test_data.py` - Common test data and fixtures
- `conftest.py` - Global test configuration and fixtures

## 🔧 Implementation patterns

### Running different test categories

Use pytest markers to run specific test types:

```bash
# Fast contract tests only (< 5 seconds)
pytest -m contract

# API integration tests (< 30 seconds)
pytest -m api

# Full test suite
pytest

# Specific test types
pytest -m "service or repository"  # Business logic tests
pytest -m "not integration"        # Skip slow tests
pytest tests/test_api/             # Just API tests
```

### Contract test pattern

Contract tests verify API communication without business logic:

```python
# Consumer test - does client send correct format?
@pytest.mark.contract
async def test_create_conversation_form_contract(page: Page):
    pact.given("user authenticated")
        .upon_receiving("conversation creation request")
        .with_request(
            method="POST",
            path="/conversations",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body="invitee_username=test&initial_message=hello"
        )
        .will_respond_with(status=303)

# Provider test - can API parse the request?
@pytest.mark.contract
def test_conversation_api_contract_verification(provider_server):
    """Verify API can handle consumer's request format."""
    verification.verify_pact(provider_server)
```

### API integration test pattern

API tests verify complete request/response workflows:

```python
@pytest.mark.api
async def test_create_conversation_success(client, authenticated_user, online_user):
    """Test complete conversation creation workflow."""
    form_data = {
        "invitee_username": online_user.username,
        "initial_message": "Hello there!"
    }

    response = await client.post("/conversations", data=form_data)

    # Verify HTTP response
    assert response.status_code == 303
    assert "conversations/" in response.headers["location"]

    # Verify business logic executed
    conversation = await get_conversation_from_db(response.headers["location"])
    assert conversation.creator_id == authenticated_user.id
    assert len(conversation.messages) == 1
```

### Service unit test pattern

Service tests focus on business logic with mocked repositories:

```python
@pytest.mark.service
async def test_conversation_service_validates_online_user(mock_user_repo, mock_conv_repo):
    """Service should reject invitations to offline users."""
    # Setup mocks
    mock_user_repo.get_user_by_username.return_value = User(is_online=False)

    service = ConversationService(mock_conv_repo, mock_user_repo)

    # Test business rule
    with pytest.raises(BusinessRuleError, match="not online"):
        await service.create_conversation(creator, "offline_user", "message")

    # Verify no database calls made
    mock_conv_repo.create.assert_not_called()
```

### Repository integration test pattern

Repository tests verify database operations with real database:

```python
@pytest.mark.repository
async def test_conversation_repository_creates_with_relationships(test_db_session):
    """Repository should create conversation with proper relationships."""
    repo = ConversationRepository(test_db_session)

    conversation = await repo.create_new_conversation(
        creator_user=creator,
        invitee_user=invitee,
        initial_message_content="Hello"
    )

    # Verify database state
    assert conversation.id is not None
    assert len(conversation.participants) == 2
    assert len(conversation.messages) == 1
    assert conversation.messages[0].content == "Hello"
```

## 🚨 Common testing issues and solutions

### Issue: Slow test execution

**Problem**: Tests take too long, slowing down development feedback
**Solution**: Use proper test markers and run subsets during development

```bash
# Development - run fast tests only
pytest -m "not integration" --maxfail=1

# CI/CD - run full suite
pytest --cov=src --cov-report=html
```

### Issue: Test data pollution

**Problem**: Tests interfere with each other through shared database state
**Solution**: Use proper test isolation and cleanup

```python
# Use pytest fixtures for clean test data
@pytest.fixture
async def clean_conversation(test_db_session):
    conversation = await create_test_conversation()
    yield conversation
    # Cleanup handled by test framework
```

### Issue: Flaky authentication tests

**Problem**: Authentication tests fail intermittently
**Solution**: Use consistent test user fixtures

```python
@pytest.fixture
async def authenticated_user(client):
    """Provides consistently authenticated user for tests."""
    user = await create_test_user(username="testuser", is_online=True)
    await client.login(user)
    return user
```

## 📋 Test configuration and markers

Configure pytest behavior in `pytest.ini`:

```ini
[tool:pytest]
markers =
    contract: Contract tests for API compatibility (fast)
    api: API integration tests (medium speed)
    service: Service layer unit tests (fast)
    repository: Repository integration tests (medium speed)
    integration: Full end-to-end tests (slow)

testpaths = tests
asyncio_mode = auto
```

Run specific test types:

```bash
# Contract tests - verify API communication
pytest -m contract tests/test_contract/

# API tests - verify endpoint behavior
pytest -m api tests/test_api/

# Development subset - fast feedback
pytest -m "contract or service" --maxfail=3

# Full test suite with coverage
pytest --cov=src --cov-report=term-missing
```

## 📚 Related documentation

- test_contract/README.md](test_contract/README.md) - Detailed contract testing philosophy and implementation
- ../src/README.md](../src/README.md) - Application architecture being tested
- ../deployment/README.md](../deployment/README.md) - CI/CD pipeline integration with tests
