# Tests: API testing for auth and user functionality

The `tests/` directory contains **API-level tests** for the Bedlam Connect application, verifying authentication workflows and user functionality through FastAPI test client integration tests.

## Core philosophy: Focused API testing

Our testing approach focuses on **verifying HTTP endpoints** with real database interactions, ensuring authentication flows and user operations work correctly end-to-end.

### What we do

- **Functional API testing**: FastAPI test client tests verifying auth and user workflows
- **Integration testing**: End-to-end tests with real database
- **Isolated testing**: Each test runs with clean database state
- **Performance-focused**: Fast test execution through proper test data management

**Example**: API integration test:

```python
@pytest.mark.api
async def test_register_and_login(client):
    """Test complete registration and login workflow."""
    # Register
    response = await client.post("/auth/register", data=form_data)
    assert response.status_code == 303

    # Login
    response = await client.post("/auth/login", data=login_data)
    assert response.status_code == 303
```

### What we don't do

- **Flaky tests**: Tests that fail intermittently due to race conditions or timing issues
- **Slow test feedback**: All tests run quickly
- **Test data pollution**: Each test is isolated with clean test data
- **Testing implementation details**: Focus on behavior and outcomes, not internal structure

## Test structure

### Current test files

- **`test_api/test_auth.py`** - 18 tests covering authentication:
  - Registration (success, validation, duplicate handling)
  - Login (success, invalid credentials)
  - Logout and session management
  - Protected route access

- **`test_api/test_users.py`** - 3 tests covering user functionality:
  - Profile page access
  - User operations

### Directory structure

**Core test directories:**

- `test_api/` - FastAPI route testing with business logic verification
  - `test_auth.py` - Authentication and authorization testing
  - `test_users.py` - User profile and operations testing

**Supporting files:**

- `shared_test_data.py` - Common test data and fixtures
- `conftest.py` - Global test configuration and fixtures

## Running tests

```bash
# Full test suite
pytest

# API tests only
pytest tests/test_api/

# Specific test files
pytest tests/test_api/test_auth.py
pytest tests/test_api/test_users.py

# With verbose output
pytest -v

# With coverage
pytest --cov=src --cov-report=term-missing

# Stop on first failure (fast feedback during development)
pytest --maxfail=1
```

## Common testing issues and solutions

### Issue: Test data pollution

**Problem**: Tests interfere with each other through shared database state
**Solution**: Use proper test isolation and cleanup via fixtures

```python
# Use pytest fixtures for clean test data
@pytest.fixture
async def authenticated_user(client):
    """Provides consistently authenticated user for tests."""
    user = await create_test_user(username="testuser")
    await client.login(user)
    return user
```

### Issue: Flaky authentication tests

**Problem**: Authentication tests fail intermittently
**Solution**: Use consistent test user fixtures

```python
@pytest.fixture
async def authenticated_user(client):
    """Provides consistently authenticated user for tests."""
    user = await create_test_user(username="testuser")
    await client.login(user)
    return user
```

## Related documentation

- [../src/README.md](../src/README.md) - Application architecture being tested
- [../deployment/README.md](../deployment/README.md) - CI/CD pipeline integration with tests
