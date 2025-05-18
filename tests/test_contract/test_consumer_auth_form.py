# tests/contract/test_consumer_auth_form.py
import atexit

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.test_helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)

CONSUMER_NAME = "registration-form"
PROVIDER_NAME = "auth-api"

# Test Constants
TEST_EMAIL = "test.user@example.com"
TEST_PASSWORD = "securepassword123"
TEST_USERNAME = "testuser"
PROVIDER_STATE_USER_DOES_NOT_EXIST = f"User {TEST_EMAIL} does not exist"
REGISTER_API_PATH = "/auth/register"
NETWORK_TIMEOUT_MS = 500


@pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_registration_form_interaction(
    origin_with_routes: str, page: Page
):
    """
    Test navigating to the registration page, filling the form,
    and submitting it correctly to the backend API (verified by Pact).
    """
    pact = setup_pact(CONSUMER_NAME, PROVIDER_NAME, port=1234)
    mock_server_uri = pact.uri
    register_page_url = f"{origin_with_routes}{REGISTER_API_PATH}"
    full_mock_url = f"{mock_server_uri}{REGISTER_API_PATH}"

    # Define Pact Interaction
    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {
        "email": Like(TEST_EMAIL),
        "password": Like(TEST_PASSWORD),
        "username": Like(TEST_USERNAME),
    }

    (
        pact.given(PROVIDER_STATE_USER_DOES_NOT_EXIST)
        .upon_receiving("a request to register a new user via web form")
        .with_request(
            method="POST",
            path=REGISTER_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(201)
    )

    # Define Playwright Interception Logic
    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=REGISTER_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    # Execute Test with Pact Verification
    with pact:
        await page.goto(register_page_url)
        await page.wait_for_selector("#email")
        await page.locator("#email").fill(TEST_EMAIL)
        await page.locator("#password").fill(TEST_PASSWORD)
        await page.locator("#username").fill(TEST_USERNAME)
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
