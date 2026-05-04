"""Consumer contract: filling and submitting the edit-post form.

Verifies that the form rendered by `templates/posts/edit.html` (mounted via
the `posts_pages` flag on the consumer server) issues `PATCH /posts/{id}`
with a JSON body matching `PostUpdate` (title + body, no `owner_id`). The
contract surface is the form template and the route's request shape.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_POST_EDIT,
    EDITED_POST_BODY,
    EDITED_POST_TITLE,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_POST_EDIT,
    POST_EDIT_API_PATH,
    POST_EDIT_PAGE_PATH,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POST_EXISTS_AND_OWNED,
    STUB_POST_ID,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"posts_pages": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_post_edit_form_interaction(origin_with_routes: str, page: Page):
    """Submit the edit-post form; assert the intercepted request matches the
    contracted shape (PATCH /posts/{id} with JSON title + body)."""
    pact = setup_pact(
        CONSUMER_NAME_POST_EDIT,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_POST_EDIT,
    )
    mock_server_uri = pact.uri
    edit_page_url = f"{origin_with_routes}{POST_EDIT_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{POST_EDIT_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {
        "title": Like(EDITED_POST_TITLE),
        "body": Like(EDITED_POST_BODY),
    }
    expected_response_body = {
        "id": Like(str(STUB_POST_ID)),
        "title": Like(EDITED_POST_TITLE),
        "body": Like(EDITED_POST_BODY),
    }

    (
        pact.given(PROVIDER_STATE_POST_EXISTS_AND_OWNED)
        .upon_receiving("a request to edit a post via the edit-post form")
        .with_request(
            method="PATCH",
            path=POST_EDIT_API_PATH,
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
        api_path_to_intercept=POST_EDIT_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="PATCH",
    )

    with pact:
        await page.goto(edit_page_url)
        await page.wait_for_selector("#title")
        await page.locator("#title").fill(EDITED_POST_TITLE)
        await page.locator("#body").fill(EDITED_POST_BODY)
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
