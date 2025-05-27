"""Shared constants for contract tests."""

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"

# API paths
REGISTER_API_PATH = "/auth/register"
INVITATIONS_PATH = "/users/me/invitations"
PARTICIPANTS_API_PATH = "/participants"

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_HAS_INVITATIONS = "user has pending invitations"
PROVIDER_STATE_USER_ONLINE = "User is online"

# Mock IDs
MOCK_PARTICIPANT_ID = "550e8400-e29b-41d4-a716-446655440000"

# Timeouts
NETWORK_TIMEOUT_MS = 500
