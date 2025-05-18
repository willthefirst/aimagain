# tests/test_contract/test_consumer_conversation_form.py
import pytest
from playwright.async_api import Page, Route, expect
from pact import Like

from tests.test_contract.test_helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

CONSUMER_NAME = "create-conversation-form"
PROVIDER_NAME = "conversations-api"

# Test Constants
TEST_INVITEE_USERNAME = "testuser2"
TEST_MESSAGE = "Hello there!"
CONVERSATIONS_NEW_PATH = "/conversations/new"
CONVERSATIONS_CREATE_PATH = "/conversations"
MOCK_CONVERSATION_SLUG = "mock-slug"
MOCK_CONVERSATION_GET_PATH = "/conversations/mock-slug"
PROVIDER_STATE_USER_ONLINE = (
    f"user is authenticated and target user exists and is online"
)

NETWORK_TIMEOUT_MS = 500


@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_conversation_create_success(
    origin_with_routes: str, page: Page
):
    """
    Test the conversation creation flow - navigating to the form page,
    filling out the form, and submitting it with a valid username.
    """
    # Use origin_with_routes instead of origin
    origin = origin_with_routes

    pact = setup_pact(CONSUMER_NAME, PROVIDER_NAME, port=1235)
    mock_server_uri = pact.uri
    new_conversation_url = f"{origin}{CONVERSATIONS_NEW_PATH}"
    form_submit_url = f"{origin}{CONVERSATIONS_CREATE_PATH}"
    mock_submit_url = f"{mock_server_uri}{CONVERSATIONS_CREATE_PATH}"

    # Define Pact Interaction for successful form submission
    expected_request_body = f"invitee_username={TEST_INVITEE_USERNAME}&initial_message={TEST_MESSAGE.replace(' ', '%20')}"
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

    (
        pact.given(PROVIDER_STATE_USER_ONLINE)
        .upon_receiving("a request to create a new conversation with valid username")
        .with_request(
            method="POST",
            path=CONVERSATIONS_CREATE_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=303, headers={"Location": f"/conversations/{MOCK_CONVERSATION_SLUG}"}
        )
    )

    (
        pact.given(PROVIDER_STATE_USER_ONLINE)
        .upon_receiving("a request to view the newly created conversation")
        .with_request(
            method="GET",
            path=f"/conversations/{MOCK_CONVERSATION_SLUG}",
        )
        .will_respond_with(status=200)
    )

    # Define Playwright Interception Logic
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=CONVERSATIONS_CREATE_PATH,
        mock_pact_url=mock_submit_url,  # This is pact.uri + CONVERSATIONS_CREATE_PATH
        http_method="POST",
    )

    async def handle_get_conversation_on_success_route(route: Route):
        print("received the get, aborting")
        await route.abort()

    await page.route(
        f"**{MOCK_CONVERSATION_GET_PATH}", handle_get_conversation_on_success_route
    )

    # Execute Test with Pact Verification
    with pact:
        await page.goto(new_conversation_url)
        await page.locator("input[name='invitee_username']").fill(TEST_INVITEE_USERNAME)
        await page.locator("textarea[name='initial_message']").fill(TEST_MESSAGE)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
