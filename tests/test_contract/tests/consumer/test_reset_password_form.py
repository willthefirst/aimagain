import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_RESET_PASSWORD,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_RESET_PASSWORD,
    PROVIDER_NAME_AUTH,
    PROVIDER_STATE_RESET_PASSWORD_TOKEN_IS_VALID,
    RESET_PASSWORD_API_PATH,
    TEST_NEW_PASSWORD,
    TEST_RESET_PASSWORD_TOKEN,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize("origin_with_routes", [{"auth_pages": True}], indirect=True)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_reset_password_form_interaction(
    origin_with_routes: str, page: Page
):
    """The reset-password form must POST JSON
    `{"token": ..., "password": ...}` to `/auth/reset-password`. The
    token rides in a hidden input populated by the page route; the
    Pact pair pins both the JSON Content-Type and the body shape so
    a regression to form-encoding (or to a missing field) flips this
    test before it ships."""
    pact = setup_pact(
        CONSUMER_NAME_RESET_PASSWORD,
        PROVIDER_NAME_AUTH,
        port=PACT_PORT_RESET_PASSWORD,
    )
    mock_server_uri = pact.uri
    # `/auth/reset-password/{token}` is the GET page route; the form
    # submits to the unsuffixed `/auth/reset-password` endpoint.
    reset_page_url = (
        f"{origin_with_routes}{RESET_PASSWORD_API_PATH}/{TEST_RESET_PASSWORD_TOKEN}"
    )
    full_mock_url = f"{mock_server_uri}{RESET_PASSWORD_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {
        "token": Like(TEST_RESET_PASSWORD_TOKEN),
        "password": Like(TEST_NEW_PASSWORD),
    }

    (
        pact.given(PROVIDER_STATE_RESET_PASSWORD_TOKEN_IS_VALID)
        .upon_receiving("a request to reset-password via web form")
        .with_request(
            method="POST",
            path=RESET_PASSWORD_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(200)
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=RESET_PASSWORD_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(reset_page_url)
        await page.wait_for_selector("#password")
        await page.locator("#password").fill(TEST_NEW_PASSWORD)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
