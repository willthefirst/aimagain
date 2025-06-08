"""Shared constants for contract tests."""

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"
TEST_INVITEE_USERNAME = "shared_testuser"
TEST_INITIAL_MESSAGE = "Hello from shared data!"
TEST_MESSAGE_CONTENT = "This is a test message for contract testing!"

# API paths
REGISTER_API_PATH = "/auth/register"
INVITATIONS_PATH = "/users/me/invitations"
PARTICIPANTS_API_PATH = "/participants"
CONVERSATIONS_PATH = "/conversations"

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_HAS_INVITATIONS = "user has pending invitations"
PROVIDER_STATE_USER_ONLINE = "User is online"

# Consumer names
CONSUMER_NAME_REGISTRATION = "registration-form"
CONSUMER_NAME_INVITATION = "invitation-form"
CONSUMER_NAME_CONVERSATION = "create-conversation-form"
CONSUMER_NAME_MESSAGE = "send-message-form"
CONSUMER_NAME_HTTPS = "https-enforcement"

# Provider names
PROVIDER_NAME_AUTH = "auth-api"
PROVIDER_NAME_PARTICIPANTS = "participants-api"
PROVIDER_NAME_CONVERSATIONS = "conversations-api"
PROVIDER_NAME_MESSAGES = "messages-api"

# Mock IDs
MOCK_PARTICIPANT_ID = "550e8400-e29b-41d4-a716-446655440000"

# Timeouts
NETWORK_TIMEOUT_MS = 500

# Pact ports
PACT_PORT_AUTH = 1234
PACT_PORT_INVITATION_ACCEPT = 1236
PACT_PORT_INVITATION_REJECT = 1237
PACT_PORT_CONVERSATION = 1235
PACT_PORT_MESSAGE = 1238
