"""Consumer contract: clicking Deactivate on the admin-actions partial.

Verifies that the HTMX-decorated button rendered by
`templates/users/_admin_actions.html` (mounted via the `users_admin_actions`
stub on the consumer server) issues a `PUT /users/{id}/activation` with a
JSON body of `{"state": "deactivated"}`. The contract surface is the partial
plus the consuming page; the body and method must agree with the route on
the provider side.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_USER_ADMIN_ACTIONS,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_USER_ACTIVATION,
    PROVIDER_NAME_USERS,
    PROVIDER_STATE_USER_EXISTS_AND_ACTIVE,
    TARGET_USER_ID,
    USER_ACTIVATION_API_PATH,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"users_admin_actions": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_deactivate_button_click(origin_with_routes: str, page: Page):
    """Click the Deactivate button on a stubbed user-detail page; assert the
    intercepted request matches the contracted shape."""
    pact = setup_pact(
        CONSUMER_NAME_USER_ADMIN_ACTIONS,
        PROVIDER_NAME_USERS,
        port=PACT_PORT_USER_ACTIVATION,
    )
    mock_server_uri = pact.uri
    detail_page_url = f"{origin_with_routes}/users/{TARGET_USER_ID}"
    full_mock_url = f"{mock_server_uri}{USER_ACTIVATION_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {"state": "deactivated"}
    expected_response_body = {
        "id": Like(str(TARGET_USER_ID)),
        "username": Like("target_user"),
        "is_active": False,
    }

    (
        pact.given(PROVIDER_STATE_USER_EXISTS_AND_ACTIVE)
        .upon_receiving("a request to deactivate a user via the admin actions partial")
        .with_request(
            method="PUT",
            path=USER_ACTIVATION_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "application/json"},
            body=expected_response_body,
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=USER_ACTIVATION_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="PUT",
    )

    # Auto-dismiss the `hx-confirm` browser dialog so the click proceeds.
    page.on("dialog", lambda dialog: dialog.accept())

    with pact:
        await page.goto(detail_page_url)
        await page.wait_for_selector("span.admin-actions button")
        await page.locator("span.admin-actions button", has_text="Deactivate").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
