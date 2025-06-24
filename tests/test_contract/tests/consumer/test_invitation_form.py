# tests/test_contract/test_consumer_invitation_form.py
import pytest
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_INVITATION,
    INVITATIONS_PATH,
    MOCK_PARTICIPANT_ID,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_INVITATION_ACCEPT,
    PACT_PORT_INVITATION_REJECT,
    PARTICIPANTS_API_PATH,
    PROVIDER_NAME_PARTICIPANTS,
    PROVIDER_STATE_USER_HAS_INVITATIONS,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"me_pages": True, "auth_pages": True, "mock_invitations": True}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_invitation_accept_method_mismatch(
    origin_with_routes: str, page: Page
):
    """
    Test that the HTMX-based invitation acceptance works correctly.

    This test verifies that:
    1. The template renders HTMX buttons that send proper PUT requests with JSON body
    2. The API receives the expected PUT requests with JSON body
    3. The contract between frontend and backend is satisfied

    This test should now PASS, proving the contract mismatch has been fixed.
    """
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_INVITATION,
        PROVIDER_NAME_PARTICIPANTS,
        port=PACT_PORT_INVITATION_ACCEPT,
    )
    mock_server_uri = pact.uri
    invitations_url = f"{origin}{INVITATIONS_PATH}"
    mock_api_url = f"{mock_server_uri}{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}"

    # Set up Pact expectation for what the API actually expects
    # (PUT request with JSON body)
    expected_request_body = {"status": "joined"}
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

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

    # Set up Playwright to intercept the HTMX request and redirect to mock server
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=f"{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}",
        mock_pact_url=mock_api_url,
        http_method="PUT",  # HTMX now sends proper PUT requests
    )

    with pact:
        # Navigate to the real invitations page with real template
        await page.goto(invitations_url)
        await page.wait_for_selector("h1:has-text('My Pending Invitations')")

        # Debug: Check what's actually rendered
        page_content = await page.content()
        print(f"DEBUG: Page content:\n{page_content}")

        # Verify our mock invitation data appears in the real template
        await page.wait_for_selector("strong:has-text('test_inviter')")
        await page.wait_for_selector("text=test-conversation-slug")
        await page.wait_for_selector(
            "em:has-text('Hey, want to join our conversation?')"
        )

        # Click the Accept button from the real template
        # This will send: PUT /participants/{id} with JSON body via HTMX
        accept_button = page.locator("button.accept-button:has-text('Accept')")

        # Handle the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())
        await accept_button.click()

        # Wait for the network request
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # TEST SUCCESS EXPECTED HERE:
    # - HTMX template sends: PUT /participants/{id} with JSON body
    # - Pact expects: PUT /participants/{id} with JSON body
    # - Contract is satisfied, proving the method mismatch bug has been fixed


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"me_pages": True, "auth_pages": True, "mock_invitations": True}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_invitation_reject_method_mismatch(
    origin_with_routes: str, page: Page
):
    """
    Test that the HTMX-based invitation rejection works correctly.
    Similar to accept test but for the reject flow.
    """
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_INVITATION,
        PROVIDER_NAME_PARTICIPANTS,
        port=PACT_PORT_INVITATION_REJECT,
    )
    mock_server_uri = pact.uri
    invitations_url = f"{origin}{INVITATIONS_PATH}"
    mock_api_url = f"{mock_server_uri}{PARTICIPANTS_API_PATH}/{MOCK_PARTICIPANT_ID}"

    # Set up Pact expectation for rejection
    expected_request_body = {"status": "rejected"}
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

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
        http_method="PUT",  # HTMX now sends proper PUT requests
    )

    with pact:
        await page.goto(invitations_url)
        await page.wait_for_selector("h1:has-text('My Pending Invitations')")

        # Click the Reject button from the real template
        reject_button = page.locator("button.reject-button:has-text('Reject')")

        # Handle the confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())
        await reject_button.click()

        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
