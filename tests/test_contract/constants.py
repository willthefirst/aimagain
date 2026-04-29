"""Shared constants for contract tests."""

import uuid

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"

# API paths
REGISTER_API_PATH = "/auth/register"
POSTS_API_PATH = "/posts"
POSTS_FORM_PAGE_PATH = "/posts/form"

# Stable target-user id used by the admin-actions stub + activation pact.
# Matches `STUB_TARGET_USER_ID` in `infrastructure/servers/consumer.py`.
TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ACTIVATION_API_PATH = f"/users/{TARGET_USER_ID}/activation"

# Stable post id returned by the post-create handler mock so the consumer can
# match the response shape and the redirect headers without round-tripping a DB.
# Also used as the path id for the edit-form and owner-actions pacts.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
POST_EDIT_API_PATH = f"/posts/{STUB_POST_ID}"
POST_EDIT_PAGE_PATH = f"/posts/{STUB_POST_ID}/form"
POST_DELETE_API_PATH = f"/posts/{STUB_POST_ID}"
POST_DETAIL_PAGE_PATH = f"/posts/{STUB_POST_ID}"

# Test post data for the create-form contract.
TEST_POST_TITLE = "Hello from contract test"
TEST_POST_BODY = "This is the body of the post."
EDITED_POST_TITLE = "Edited title"
EDITED_POST_BODY = "Edited body"

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_EXISTS_AND_ACTIVE = f"User {TARGET_USER_ID} exists and is active"
PROVIDER_STATE_POSTS_ACCEPTS_CREATE = "Posts API accepts a create request"
PROVIDER_STATE_POST_EXISTS_AND_OWNED = (
    f"Post {STUB_POST_ID} exists and is owned by the requester"
)

# Consumer / provider Pact identifiers
CONSUMER_NAME_REGISTRATION = "registration-form"
PROVIDER_NAME_AUTH = "auth-api"

CONSUMER_NAME_USER_ADMIN_ACTIONS = "user-admin-actions"
PROVIDER_NAME_USERS = "users-api"

CONSUMER_NAME_POST_CREATE = "post-create-form"
CONSUMER_NAME_POST_EDIT = "post-edit-form"
CONSUMER_NAME_POST_OWNER_ACTIONS = "post-owner-actions"
PROVIDER_NAME_POSTS = "posts-api"

# Timeouts
NETWORK_TIMEOUT_MS = 500

# Pact ports (one port per consumer-provider pair)
PACT_PORT_AUTH = 1234
PACT_PORT_USER_ACTIVATION = 1235
PACT_PORT_POST_CREATE = 1236
PACT_PORT_POST_EDIT = 1237
PACT_PORT_POST_DELETE = 1238
