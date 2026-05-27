"""Shared constants for contract tests."""

import uuid

# Test user data
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"

# API paths
REGISTER_API_PATH = "/auth/register"
FORGOT_PASSWORD_API_PATH = "/auth/forgot-password"
RESET_PASSWORD_API_PATH = "/auth/reset-password"

# Reset-password token surface. The token is a JWT produced by
# `BaseUserManager.forgot_password` in production; for contract testing
# we only care that the consumer's hidden input round-trips a token
# string the route's body schema accepts (it's a plain `str`, no JWT
# validation at the parsing layer — that's deferred to `reset_password`,
# which the provider verification mocks out).
TEST_RESET_PASSWORD_TOKEN = "test-reset-password-token"
TEST_NEW_PASSWORD = "newpassword456"

# Stable target-user id used by the admin-actions stub + activation pact.
# Matches `STUB_TARGET_USER_ID` in `infrastructure/servers/consumer.py`.
TARGET_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ACTIVATION_API_PATH = f"/users/{TARGET_USER_ID}/activation"

# Stable post id used as the path id for the owner-actions pact.
# Post-#628 the URL family is per-kind; `referral` is the canonical
# kind for this contract — the owner-actions partial is shared across
# all three families and the HTMX wire shape is identical, so picking
# one kind covers the contract surface (the consumer stub mounts
# `/referrals/{post_id}`).
STUB_POST_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
POST_DELETE_API_PATH = f"/referrals/{STUB_POST_ID}"
POST_DETAIL_PAGE_PATH = f"/referrals/{STUB_POST_ID}"

# Clinician (formerly "provider") create form pact. URL family flipped
# from `/providers` to `/clinicians` in #642 PR 4; the Pact participant
# names (`CONSUMER_NAME_PROVIDER_*`, `PROVIDER_NAME_PROVIDERS`) keep
# their historical identity so the pact-broker history reads
# continuously across the rename.
CLINICIAN_CREATE_API_PATH = "/clinicians"
CLINICIAN_CREATE_FORM_PAGE_PATH = "/clinicians/form"

# Clinician edit form pact: parent practice-fields PATCH only.
# (Sub-resource pacts — licensures, educations, certifications — deferred.)
STUB_CLINICIAN_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
CLINICIAN_PATCH_API_PATH = f"/clinicians/{STUB_CLINICIAN_ID}"
CLINICIAN_EDIT_FORM_PAGE_PATH = f"/clinicians/{STUB_CLINICIAN_ID}/form"

# Organization create form pact.
# `?type=clinic` bypasses the type-picker added in #704 and lands
# directly on the create form with the Type dropdown pre-selected.
ORGANIZATION_CREATE_API_PATH = "/organizations"
ORGANIZATION_CREATE_FORM_PAGE_PATH = "/organizations/form?type=clinic"

# Program create form pact. Programs attach to an existing Organization
# via the form's `org_id` dropdown; the consumer stub seeds one Org
# (`STUB_PROGRAM_FORM_ORG_ID`) so the pact body is deterministic.
PROGRAM_CREATE_API_PATH = "/programs"
PROGRAM_CREATE_FORM_PAGE_PATH = "/programs/form"
STUB_PROGRAM_FORM_ORG_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")

# Provider states
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
PROVIDER_STATE_USER_CAN_REQUEST_PASSWORD_RESET = (
    f"User {TEST_EMAIL} can request a password reset"
)
PROVIDER_STATE_RESET_PASSWORD_TOKEN_IS_VALID = (
    "Reset password token is valid for an active user"
)
PROVIDER_STATE_USER_EXISTS_AND_ACTIVE = f"User {TARGET_USER_ID} exists and is active"
PROVIDER_STATE_POST_EXISTS_AND_OWNED = (
    f"Post {STUB_POST_ID} exists and is owned by the requester"
)
PROVIDER_STATE_USER_CAN_CREATE_PROVIDER = "User can create a provider"
PROVIDER_STATE_PROVIDER_EXISTS_AND_OWNED = (
    f"Provider {STUB_CLINICIAN_ID} exists and is owned by the requester"
)
PROVIDER_STATE_USER_CAN_CREATE_ORGANIZATION = "User can create an organization"
PROVIDER_STATE_USER_CAN_CREATE_PROGRAM = "User can create a program"

# Consumer / provider Pact identifiers
CONSUMER_NAME_REGISTRATION = "registration-form"
CONSUMER_NAME_FORGOT_PASSWORD = "forgot-password-form"
CONSUMER_NAME_RESET_PASSWORD = "reset-password-form"
PROVIDER_NAME_AUTH = "auth-api"

CONSUMER_NAME_USER_ADMIN_ACTIONS = "user-admin-actions"
PROVIDER_NAME_USERS = "users-api"

CONSUMER_NAME_POST_OWNER_ACTIONS = "post-owner-actions"
PROVIDER_NAME_POSTS = "posts-api"

CONSUMER_NAME_CLINICIAN_CREATE_FORM = "provider-create-form"
CONSUMER_NAME_CLINICIAN_EDIT_FORM = "provider-edit-form"
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
PACT_PORT_CLINICIAN_CREATE = 1239
PACT_PORT_CLINICIAN_EDIT = 1240
PACT_PORT_ORGANIZATION_CREATE = 1241
PACT_PORT_PROGRAM_CREATE = 1242
PACT_PORT_FORGOT_PASSWORD = 1243
PACT_PORT_RESET_PASSWORD = 1244
