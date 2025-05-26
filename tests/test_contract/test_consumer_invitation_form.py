# tests/test_contract/test_consumer_invitation_form.py
import multiprocessing
import uuid
from typing import Any, Dict

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.async_api import Page

from app.api.routes import auth_pages, me
from app.auth_config import current_active_user
from app.models import Conversation, Message, Participant, User
from app.schemas.participant import ParticipantStatus
from app.services.user_service import UserService
from tests.test_contract.conftest import (
    CONSUMER_BASE_URL,
    CONSUMER_HOST,
    CONSUMER_PORT,
    _create_mock_user,
    _poll_server_ready,
    _terminate_server_process,
)
from tests.test_contract.test_helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

CONSUMER_NAME = "invitation-form"
PROVIDER_NAME = "participants-api"

# Test Constants
INVITATIONS_PATH = "/users/me/invitations"
PARTICIPANTS_API_PATH = "/participants"
MOCK_PARTICIPANT_ID = "550e8400-e29b-41d4-a716-446655440000"
PROVIDER_STATE_USER_HAS_INVITATIONS = "user has pending invitations"

NETWORK_TIMEOUT_MS = 500


def _create_mock_invitation_data():
    """Creates mock invitation data that matches what the template expects."""
    # Create mock User objects
    mock_inviter = User(
        id=uuid.uuid4(),
        email="inviter@example.com",
        username="test_inviter",
        is_active=True,
    )

    mock_conversation = Conversation(
        id=uuid.uuid4(),
        slug="test-conversation-slug",
        created_by_user_id=mock_inviter.id,
    )

    mock_initial_message = Message(
        id=uuid.uuid4(),
        content="Hey, want to join our conversation?",
        conversation_id=mock_conversation.id,
        created_by_user_id=mock_inviter.id,
    )

    # Create mock Participant (invitation) with relationships
    mock_invitation = Participant(
        id=uuid.UUID(MOCK_PARTICIPANT_ID),
        user_id=uuid.uuid4(),  # Current user's ID
        conversation_id=mock_conversation.id,
        status=ParticipantStatus.INVITED,
        invited_by_user_id=mock_inviter.id,
        initial_message_id=mock_initial_message.id,
    )

    # Set up the relationships that the template accesses
    mock_invitation.inviter = mock_inviter
    mock_invitation.conversation = mock_conversation
    mock_invitation.initial_message = mock_initial_message

    return [mock_invitation]


def run_consumer_server_with_mock_invitations(host: str, port: int):
    """Runs consumer server with mocked invitations data."""
    from app.services.dependencies import get_user_service

    consumer_app = FastAPI(title="Consumer Test Server with Mock Invitations")

    @consumer_app.get("/_health")
    async def health_check():
        return {"status": "ok"}

    # Include the routes we need
    consumer_app.include_router(auth_pages.auth_pages_api_router)
    consumer_app.include_router(me.me_router_instance)

    # Mock auth
    mock_user = _create_mock_user(
        email="test@example.com", username="contract_test_user"
    )

    async def get_mock_current_user():
        return mock_user

    consumer_app.dependency_overrides[current_active_user] = get_mock_current_user

    # Mock user service to return our fake invitations
    mock_invitations = _create_mock_invitation_data()

    class MockUserService:
        async def get_user_invitations(self, user: User):
            return mock_invitations

        async def get_user_conversations(self, user: User):
            return []

    async def get_mock_user_service():
        return MockUserService()

    consumer_app.dependency_overrides[get_user_service] = get_mock_user_service

    uvicorn.run(consumer_app, host=host, port=port, log_level="warning")


@pytest.fixture(scope="function")
def consumer_server_with_mock_invitations():
    """Starts a consumer server with mock invitations data."""
    server_process = multiprocessing.Process(
        target=run_consumer_server_with_mock_invitations,
        args=(CONSUMER_HOST, CONSUMER_PORT),
        daemon=True,
    )
    server_process.start()
    health_check_url = f"http://{CONSUMER_HOST}:{CONSUMER_PORT}/_health"
    if not _poll_server_ready(health_check_url):
        _terminate_server_process(server_process)
        raise RuntimeError(
            f"Consumer server process failed to start at {health_check_url}"
        )

    yield str(CONSUMER_BASE_URL)
    _terminate_server_process(server_process)


@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_invitation_accept_method_mismatch(
    consumer_server_with_mock_invitations: str, page: Page
):
    """
    Test that reveals the method mismatch bug in invitation acceptance.

    This test demonstrates the real bug users encounter:
    1. The template renders forms that send POST with ?_method=PUT and form data
    2. The API expects actual PUT requests with JSON body
    3. Without method override middleware, POST+?_method=PUT never becomes PUT
    4. Result: 405 Method Not Allowed errors for users

    This test SHOULD FAIL, proving the contract mismatch exists.
    """
    origin = consumer_server_with_mock_invitations

    pact = setup_pact(CONSUMER_NAME, PROVIDER_NAME, port=1236)
    mock_server_uri = pact.uri
    invitations_url = f"{origin}{INVITATIONS_PATH}"
    mock_api_url = f"{mock_server_uri}{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}"

    # Set up Pact expectation for what the API actually expects
    # (PUT request with JSON body)
    expected_request_body = {"status": "joined"}
    expected_request_headers = {"Content-Type": "application/json"}

    (
        pact.given(PROVIDER_STATE_USER_HAS_INVITATIONS)
        .upon_receiving("a request to accept an invitation")
        .with_request(
            method="PUT",
            path=f"{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}",
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body={
                "id": MOCK_PARTICIPANT_ID,
                "user_id": "550e8400-e29b-41d4-a716-446655440001",
                "conversation_id": "550e8400-e29b-41d4-a716-446655440002",
                "status": "joined",
                "invited_by_user_id": "550e8400-e29b-41d4-a716-446655440003",
                "initial_message_id": "550e8400-e29b-41d4-a716-446655440004",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "joined_at": "2024-01-01T00:00:00Z",
            },
        )
    )

    # Set up Playwright to intercept the form submission and redirect to mock server
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=f"{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}",
        mock_pact_url=mock_api_url,
        http_method="POST",  # The form actually sends POST, not PUT
    )

    with pact:
        # Navigate to the real invitations page with real template
        await page.goto(invitations_url)
        await page.wait_for_selector("h1:has-text('My Pending Invitations')")

        # Verify our mock invitation data appears in the real template
        await page.wait_for_selector("strong:has-text('test_inviter')")
        await page.wait_for_selector("text=test-conversation-slug")
        await page.wait_for_selector(
            "em:has-text('Hey, want to join our conversation?')"
        )

        # Click the Accept button from the real template
        # This will send: POST /participants/{id}?_method=PUT with form data
        accept_button = (
            page.locator("form")
            .filter(has=page.locator("input[value='joined']"))
            .locator("button:has-text('Accept')")
        )
        await accept_button.click()

        # Wait for the network request
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # TEST FAILURE EXPECTED HERE:
    # - Real template sends: POST /participants/{id}?_method=PUT with form data
    # - Pact expects: PUT /participants/{id} with JSON body
    # - No method override middleware converts POST+_method=PUT → PUT
    # - Result: Missing PUT request, revealing the 405 Method Not Allowed bug


@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_invitation_reject_method_mismatch(
    consumer_server_with_mock_invitations: str, page: Page
):
    """
    Test that reveals the method mismatch bug in invitation rejection.
    Similar to accept test but for the reject flow.
    """
    origin = consumer_server_with_mock_invitations

    pact = setup_pact(CONSUMER_NAME, PROVIDER_NAME, port=1237)
    mock_server_uri = pact.uri
    invitations_url = f"{origin}{INVITATIONS_PATH}"
    mock_api_url = f"{mock_server_uri}{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}"

    # Set up Pact expectation for rejection
    expected_request_body = {"status": "rejected"}
    expected_request_headers = {"Content-Type": "application/json"}

    (
        pact.given(PROVIDER_STATE_USER_HAS_INVITATIONS)
        .upon_receiving("a request to reject an invitation")
        .with_request(
            method="PUT",
            path=f"{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}",
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body={
                "id": MOCK_PARTICIPANT_ID,
                "user_id": "550e8400-e29b-41d4-a716-446655440001",
                "conversation_id": "550e8400-e29b-41d4-a716-446655440002",
                "status": "rejected",
                "invited_by_user_id": "550e8400-e29b-41d4-a716-446655440003",
                "initial_message_id": "550e8400-e29b-41d4-a716-446655440004",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "joined_at": None,
            },
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=f"{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}",
        mock_pact_url=mock_api_url,
        http_method="POST",
    )

    with pact:
        await page.goto(invitations_url)
        await page.wait_for_selector("h1:has-text('My Pending Invitations')")

        # Click the Reject button from the real template
        reject_button = (
            page.locator("form")
            .filter(has=page.locator("input[value='rejected']"))
            .locator("button:has-text('Reject')")
        )
        await reject_button.click()

        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
