# tests/test_contract/tests/consumer/test_message_form.py
import pytest
from playwright.async_api import Page

from tests.shared_test_data import TEST_MESSAGE_CONTENT, get_form_encoded_message_data
from tests.test_contract.constants import (
    CONSUMER_NAME_MESSAGE,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_MESSAGE,
    PROVIDER_NAME_MESSAGES,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

# Test Constants
MOCK_CONVERSATION_SLUG = "test-conversation-slug"
CONVERSATION_DETAIL_PATH = f"/conversations/{MOCK_CONVERSATION_SLUG}"
MESSAGE_CREATE_PATH = f"/conversations/{MOCK_CONVERSATION_SLUG}/messages"
PROVIDER_STATE_USER_AUTHENTICATED = (
    "user is authenticated and has access to conversation"
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"conversations": True, "auth_pages": True, "mock_conversation_details": True}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_message_page_loads(origin_with_routes: str, page: Page):
    """
    Simple test to check if the conversation detail page loads with mock data.
    This helps debug the mock configuration.
    """
    origin = origin_with_routes
    conversation_detail_url = f"{origin}{CONVERSATION_DETAIL_PATH}"

    # Just try to load the page to see if the mock works
    try:
        await page.goto(conversation_detail_url)

        # Check if the page loaded successfully by looking for the form
        form_locator = page.locator("form[name='send-message-form']")
        await form_locator.wait_for(state="visible", timeout=5000)

        # Check if the textarea is present
        textarea_locator = page.locator("textarea[name='message_content']")
        await textarea_locator.wait_for(state="visible", timeout=5000)

        print("✅ Page loaded successfully with mock conversation data")

    except Exception as e:
        print(f"❌ Page failed to load: {e}")
        raise


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"conversations": True, "auth_pages": True, "mock_conversation_details": True}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_message_create_success(origin_with_routes: str, page: Page):
    """
    Test the message creation flow using the actual detail.html template.

    This test ensures that the form in detail.html template matches the contract
    of the POST /conversations/{slug}/messages route by verifying:
    - Form uses correct HTTP method (POST)
    - Form sends data as application/x-www-form-urlencoded
    - Form includes required field: message_content
    - API responds with 303 redirect back to conversation detail
    """
    origin = origin_with_routes

    pact = setup_pact(
        CONSUMER_NAME_MESSAGE,
        PROVIDER_NAME_MESSAGES,
        port=PACT_PORT_MESSAGE,
    )
    mock_server_uri = pact.uri
    conversation_detail_url = f"{origin}{CONVERSATION_DETAIL_PATH}"
    mock_submit_url = f"{mock_server_uri}{MESSAGE_CREATE_PATH}"

    expected_request_body = get_form_encoded_message_data()
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Set up Pact expectation for message creation
    (
        pact.given(PROVIDER_STATE_USER_AUTHENTICATED)
        .upon_receiving("a request to create a new message with valid content")
        .with_request(
            method="POST",
            path=MESSAGE_CREATE_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(status=303, headers={"Location": CONVERSATION_DETAIL_PATH})
    )

    (
        pact.upon_receiving(
            "the redirect to the conversation detail page after message creation"
        )
        .with_request(
            method="GET",
            path=CONVERSATION_DETAIL_PATH,
        )
        .will_respond_with(status=200)
    )

    # Set up Playwright interception to redirect form submission to Pact mock
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=MESSAGE_CREATE_PATH,
        mock_pact_url=mock_submit_url,
        http_method="POST",
    )

    with pact:
        # Navigate to the actual conversation detail page (which will render the real template)
        await page.goto(conversation_detail_url)

        # Fill out the message form using the actual form elements from detail.html
        await page.locator("textarea[name='message_content']").fill(
            TEST_MESSAGE_CONTENT
        )

        # Submit the form using the actual submit button from detail.html
        await page.locator("button[type='submit']").click()

        # Wait for the network request to complete
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
