import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_FORGOT_PASSWORD,
    FORGOT_PASSWORD_API_PATH,
    HONEYPOT_FIELD_NAME,
    NETWORK_TIMEOUT_MS,
    PROVIDER_NAME_AUTH,
    PROVIDER_STATE_USER_CAN_REQUEST_PASSWORD_RESET,
    TEST_EMAIL,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_forgot_password_form_interaction(
    origin_with_routes: str, page: Page
):
    """The forgot-password form must POST JSON `{"email": ...}` to
    `/auth/forgot-password`. PR #770 fixed the form to emit JSON
    instead of form-encoded; this pair pins the wire shape structurally
    so a regression flips the contract test before it ships."""
    pact = setup_pact(
        CONSUMER_NAME_FORGOT_PASSWORD,
        PROVIDER_NAME_AUTH,
    )
    mock_server_uri = pact.uri
    forgot_page_url = f"{origin_with_routes}{FORGOT_PASSWORD_API_PATH}"
    full_mock_url = f"{mock_server_uri}{FORGOT_PASSWORD_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    # The hidden anti-bot honeypot rides along as an empty string (see
    # `_shared/antibot.html` / `enforce_antibot`).
    expected_request_body = {
        "email": Like(TEST_EMAIL),
        HONEYPOT_FIELD_NAME: Like(""),
    }

    (
        pact.given(PROVIDER_STATE_USER_CAN_REQUEST_PASSWORD_RESET)
        .upon_receiving("a request to forgot-password via web form")
        .with_request(
            method="POST",
            path=FORGOT_PASSWORD_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(202)
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=FORGOT_PASSWORD_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(forgot_page_url)
        await page.wait_for_selector("#email")
        await page.locator("#email").fill(TEST_EMAIL)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
