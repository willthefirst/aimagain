import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_REGISTRATION,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_AUTH,
    PROVIDER_NAME_AUTH,
    PROVIDER_STATE_USER_DOES_NOT_EXIST,
    REGISTER_API_PATH,
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_USERNAME,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.consumer
@pytest.mark.auth
async def test_consumer_registration_form_interaction(
    origin_with_routes: str, page: Page
):
    """
    Test navigating to the registration page, filling the form,
    and submitting it correctly to the backend API (verified by Pact).
    """
    pact = setup_pact(
        CONSUMER_NAME_REGISTRATION, PROVIDER_NAME_AUTH, port=PACT_PORT_AUTH
    )
    mock_server_uri = pact.uri
    register_page_url = f"{origin_with_routes}{REGISTER_API_PATH}"
    full_mock_url = f"{mock_server_uri}{REGISTER_API_PATH}"

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
