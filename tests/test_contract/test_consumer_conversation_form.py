# tests/test_contract/test_consumer_conversation_form.py
import pytest
from playwright.async_api import Page, Route, expect
from pact import Like

# Test Constants
TEST_INVITEE_USERNAME = "testuser2"
TEST_MESSAGE = "Hello there!"
CONVERSATIONS_NEW_PATH = "/conversations/new"
CONVERSATIONS_CREATE_PATH = "/conversations"
MOCK_CONVERSATION_SLUG = "mock-slug"
PROVIDER_STATE_USER_ONLINE = (
    f"user is authenticated and target user exists and is online"
)
PROVIDER_STATE_USER_NOT_FOUND = f"user is authenticated and target user does not exist"
NETWORK_TIMEOUT_MS = 500


@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_conversation_create_success(
    pact_mock, origin_with_routes: str, page: Page
):
    """
    Test the conversation creation flow - navigating to the form page,
    filling out the form, and submitting it with a valid username.
    """
    # Use origin_with_routes instead of origin
    origin = origin_with_routes

    pact = pact_mock
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

    # Define Playwright Interception Logic
    async def handle_route(route: Route):
        if (
            route.request.method == "POST"
            and CONVERSATIONS_CREATE_PATH
            == route.request.url.split("?")[0].split("#")[0]
        ):
            await route.continue_(
                url=mock_submit_url,
                headers={
                    k: v
                    for k, v in route.request.headers.items()
                    if k.lower() != "content-length"
                },
            )
        else:
            await route.continue_()

    await page.route(f"**{CONVERSATIONS_CREATE_PATH}", handle_route)

    # Execute Test with Pact Verification
    with pact:
        # Navigate to the new conversation form
        await page.goto(new_conversation_url)

        # Fill out the form
        await page.locator("input[name='invitee_username']").fill(TEST_INVITEE_USERNAME)
        await page.locator("textarea[name='initial_message']").fill(TEST_MESSAGE)

        # Submit the form
        await page.locator("button[type='submit']").click()

        # Wait for the redirect (in a real test, we might verify we landed on the right page)
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.


@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_conversation_create_user_not_found(
    pact_mock, origin: str, page: Page
):
    """
    Test the conversation creation flow with a non-existent username,
    which should result in a 404 error.
    """
    pact = pact_mock
    mock_server_uri = pact.uri
    new_conversation_url = f"{origin}{CONVERSATIONS_NEW_PATH}"
    form_submit_url = f"{origin}{CONVERSATIONS_CREATE_PATH}"
    mock_submit_url = f"{mock_server_uri}{CONVERSATIONS_CREATE_PATH}"

    # Define the non-existent username
    NONEXISTENT_USERNAME = "nonexistentuser"

    # Define Pact Interaction for form submission with invalid username
    expected_request_body = f"invitee_username={NONEXISTENT_USERNAME}&initial_message={TEST_MESSAGE.replace(' ', '%20')}"
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

    (
        pact.given(PROVIDER_STATE_USER_NOT_FOUND)
        .upon_receiving("a request to create a conversation with non-existent username")
        .with_request(
            method="POST",
            path=CONVERSATIONS_CREATE_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=404,
            headers={"Content-Type": "application/json"},
            body={"detail": "User not found"},
        )
    )

    # Define Playwright Interception Logic
    async def handle_route(route: Route):
        if (
            route.request.method == "POST"
            and CONVERSATIONS_CREATE_PATH
            == route.request.url.split("?")[0].split("#")[0]
        ):
            await route.continue_(
                url=mock_submit_url,
                headers={
                    k: v
                    for k, v in route.request.headers.items()
                    if k.lower() != "content-length"
                },
            )
        else:
            await route.continue_()

    await page.route(f"**{CONVERSATIONS_CREATE_PATH}", handle_route)

    # Execute Test with Pact Verification
    with pact:
        # Navigate to the new conversation form
        await page.goto(new_conversation_url)

        # Verify form elements are present by interacting with them
        await page.get_by_role("button", name="Start Conversation")

        # Fill out the form with non-existent username
        await page.locator("input[name='invitee_username']").fill(NONEXISTENT_USERNAME)
        await page.locator("textarea[name='initial_message']").fill(TEST_MESSAGE)

        # Submit the form
        await page.locator("button[type='submit']").click()

        # In a real test, we might check for error message display
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
