"""Shared constants for contract tests."""

import uuid

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"

# API paths
REGISTER_API_PATH = "/auth/register"

# Stable target-user id used by the admin-actions stub + activation pact.
# Matches `STUB_TARGET_USER_ID` in `infrastructure/servers/consumer.py`.
TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ACTIVATION_API_PATH = f"/users/{TARGET_USER_ID}/activation"

# Stable post id used as the path id for the owner-actions pact.
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
POST_DELETE_API_PATH = f"/posts/{STUB_POST_ID}"
POST_DETAIL_PAGE_PATH = f"/posts/{STUB_POST_ID}"

# Provider-profile create form pact.
PROVIDER_PROFILE_CREATE_API_PATH = "/provider-profiles"
PROVIDER_PROFILE_CREATE_FORM_PAGE_PATH = "/provider-profiles/form"

# Provider-profile edit form pact: parent practice-fields PATCH only.
# (Sub-resource pacts — licensures, educations, certifications — deferred.)
STUB_PROFILE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
PROVIDER_PROFILE_PATCH_API_PATH = f"/provider-profiles/{STUB_PROFILE_ID}"
PROVIDER_PROFILE_EDIT_FORM_PAGE_PATH = f"/provider-profiles/{STUB_PROFILE_ID}/form"

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_EXISTS_AND_ACTIVE = f"User {TARGET_USER_ID} exists and is active"
PROVIDER_STATE_POST_EXISTS_AND_OWNED = (
    f"Post {STUB_POST_ID} exists and is owned by the requester"
)
PROVIDER_STATE_USER_CAN_CREATE_PROFILE = "User can create a provider profile"
PROVIDER_STATE_PROFILE_EXISTS_AND_OWNED = (
    f"Provider profile {STUB_PROFILE_ID} exists and is owned by the requester"
)

# Consumer / provider Pact identifiers
CONSUMER_NAME_REGISTRATION = "registration-form"
PROVIDER_NAME_AUTH = "auth-api"

CONSUMER_NAME_USER_ADMIN_ACTIONS = "user-admin-actions"
PROVIDER_NAME_USERS = "users-api"

CONSUMER_NAME_POST_OWNER_ACTIONS = "post-owner-actions"
PROVIDER_NAME_POSTS = "posts-api"

CONSUMER_NAME_PROVIDER_PROFILE_CREATE_FORM = "provider-profile-create-form"
CONSUMER_NAME_PROVIDER_PROFILE_EDIT_FORM = "provider-profile-edit-form"
PROVIDER_NAME_PROVIDER_PROFILES = "provider-profiles-api"

# Timeouts
NETWORK_TIMEOUT_MS = 500

# Pact ports (one port per consumer-provider pair)
PACT_PORT_AUTH = 1234
PACT_PORT_USER_ACTIVATION = 1235
PACT_PORT_POST_DELETE = 1238
PACT_PORT_PROVIDER_PROFILE_CREATE = 1239
PACT_PORT_PROVIDER_PROFILE_EDIT = 1240
