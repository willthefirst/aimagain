"""Consumer contract: clicking Delete on the post owner-actions partial.

Verifies that the HTMX-decorated button rendered by
`templates/posts/_owner_actions.html` (mounted via the `posts_owner_actions`
stub on the consumer server) issues a `DELETE /posts/{id}` and that the
response carries the `HX-Redirect: /posts` header htmx follows on success.
The contract surface is the partial plus the consuming detail page; method,
path, and the redirect header must agree with the route on the provider side.
"""

import pytest
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_POST_OWNER_ACTIONS,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_POST_DELETE,
    POST_DELETE_API_PATH,
    POST_DETAIL_PAGE_PATH,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POST_EXISTS_AND_OWNED,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"posts_owner_actions": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_delete_button_click(origin_with_routes: str, page: Page):
    """Click the Delete button on a stubbed post-detail page; assert the
    intercepted request matches the contracted shape."""
    pact = setup_pact(
        CONSUMER_NAME_POST_OWNER_ACTIONS,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_POST_DELETE,
    )
    mock_server_uri = pact.uri
    detail_page_url = f"{origin_with_routes}{POST_DETAIL_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{POST_DELETE_API_PATH}"

    (
        pact.given(PROVIDER_STATE_POST_EXISTS_AND_OWNED)
        .upon_receiving("a request to delete a post via the owner-actions partial")
        .with_request(method="DELETE", path=POST_DELETE_API_PATH)
        .will_respond_with(status=204, headers={"HX-Redirect": "/posts"})
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=POST_DELETE_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="DELETE",
    )

    # Auto-dismiss the `hx-confirm` browser dialog so the click proceeds.
    page.on("dialog", lambda dialog: dialog.accept())

    with pact:
        await page.goto(detail_page_url)
        await page.wait_for_selector("span.owner-actions button")
        await page.locator("span.owner-actions button", has_text="Delete").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
