# Contract Tests

This directory contains contract tests using the Pact framework to ensure API compatibility between consumers and providers.

## Structure

- `tests/` - All test files organized by type
  - `consumer/` - Consumer contract tests (frontend/client tests)
  - `provider/` - Provider contract tests (API verification tests)
  - `shared/` - Shared test utilities and constants
- `infrastructure/` - Test infrastructure and utilities
  - `servers/` - Server management for test environments
  - `utilities/` - Helper utilities for testing
- `artifacts/` - Generated test artifacts (gitignored)
  - `pacts/` - Generated Pact contract files
  - `logs/` - Test execution logs
  - `reports/` - Test reports
- `docs/` - Documentation and guides

## Running Tests

### Consumer Tests
```bash
# Run all consumer tests
pytest tests/consumer/

# Run specific consumer test categories
pytest tests/consumer/ -m auth
pytest tests/consumer/ -m conversations
pytest tests/consumer/ -m invitations
```

### Provider Tests
```bash
# Run provider verification tests
pytest tests/provider/
```

### All Contract Tests
```bash
# Run all contract tests
pytest tests/
```

## Test Categories

Tests are marked with the following categories:
- `consumer` - Consumer contract tests
- `provider` - Provider contract tests  
- `auth` - Authentication-related tests
- `conversations` - Conversation-related tests
- `invitations` - Invitation-related tests
- `slow` - Slow running tests

## Configuration

Test configuration is managed in `infrastructure/config.py`. Key settings include:
- Server ports and URLs
- Database configuration
- Pact directory locations
- Known provider states

## Adding New Tests

1. **Consumer Tests**: Add to appropriate subdirectory in `tests/consumer/`
2. **Provider Tests**: Add to `tests/provider/`
3. **Shared Utilities**: Add to `tests/shared/`
4. **Infrastructure**: Add to `infrastructure/`

## Troubleshooting

See `docs/TROUBLESHOOTING.md` for common issues and solutions.
