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

# Provider create form pact.
PROVIDER_CREATE_API_PATH = "/providers"
PROVIDER_CREATE_FORM_PAGE_PATH = "/providers/form"

# Provider edit form pact: parent practice-fields PATCH only.
# (Sub-resource pacts — licensures, educations, certifications — deferred.)
STUB_PROVIDER_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
PROVIDER_PATCH_API_PATH = f"/providers/{STUB_PROVIDER_ID}"
PROVIDER_EDIT_FORM_PAGE_PATH = f"/providers/{STUB_PROVIDER_ID}/form"

# Organization create form pact.
ORGANIZATION_CREATE_API_PATH = "/organizations"
ORGANIZATION_CREATE_FORM_PAGE_PATH = "/organizations/form"

# Program create form pact. Programs attach to an existing Organization
# via the form's `org_id` dropdown; the consumer stub seeds one Org
# (`STUB_PROGRAM_FORM_ORG_ID`) so the pact body is deterministic.
PROGRAM_CREATE_API_PATH = "/programs"
PROGRAM_CREATE_FORM_PAGE_PATH = "/programs/form"
STUB_PROGRAM_FORM_ORG_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_EXISTS_AND_ACTIVE = f"User {TARGET_USER_ID} exists and is active"
PROVIDER_STATE_POST_EXISTS_AND_OWNED = (
    f"Post {STUB_POST_ID} exists and is owned by the requester"
)
PROVIDER_STATE_USER_CAN_CREATE_PROVIDER = "User can create a provider"
PROVIDER_STATE_PROVIDER_EXISTS_AND_OWNED = (
    f"Provider {STUB_PROVIDER_ID} exists and is owned by the requester"
)
PROVIDER_STATE_USER_CAN_CREATE_ORGANIZATION = "User can create an organization"
PROVIDER_STATE_USER_CAN_CREATE_PROGRAM = "User can create a program"

# Consumer / provider Pact identifiers
CONSUMER_NAME_REGISTRATION = "registration-form"
PROVIDER_NAME_AUTH = "auth-api"

CONSUMER_NAME_USER_ADMIN_ACTIONS = "user-admin-actions"
PROVIDER_NAME_USERS = "users-api"

CONSUMER_NAME_POST_OWNER_ACTIONS = "post-owner-actions"
PROVIDER_NAME_POSTS = "posts-api"

CONSUMER_NAME_PROVIDER_CREATE_FORM = "provider-create-form"
CONSUMER_NAME_PROVIDER_EDIT_FORM = "provider-edit-form"
PROVIDER_NAME_PROVIDERS = "providers-api"

CONSUMER_NAME_ORGANIZATION_CREATE_FORM = "organization-create-form"
PROVIDER_NAME_ORGANIZATIONS = "organizations-api"

CONSUMER_NAME_PROGRAM_CREATE_FORM = "program-create-form"
PROVIDER_NAME_PROGRAMS = "programs-api"

# Timeouts
NETWORK_TIMEOUT_MS = 500

# Pact ports (one port per consumer-provider pair)
PACT_PORT_AUTH = 1234
PACT_PORT_USER_ACTIVATION = 1235
PACT_PORT_POST_DELETE = 1238
PACT_PORT_PROVIDER_CREATE = 1239
PACT_PORT_PROVIDER_EDIT = 1240
PACT_PORT_ORGANIZATION_CREATE = 1241
PACT_PORT_PROGRAM_CREATE = 1242
