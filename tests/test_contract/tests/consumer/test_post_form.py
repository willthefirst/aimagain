"""Consumer contract: filling and submitting the new-post form.

Verifies that the form rendered by `templates/posts/new.html` (mounted via
the `posts_pages` flag on the consumer server) issues `POST /posts` with a
JSON body matching `ClientReferralCreate` (kind + summary + urgency +
region). The contract surface is the form template — including its
per-kind field cluster — and the route's request shape.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_POST_CREATE,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_POST_CREATE,
    POSTS_API_PATH,
    POSTS_FORM_PAGE_PATH,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POSTS_ACCEPTS_CREATE,
    STUB_POST_ID,
    TEST_CLIENT_REFERRAL_REGION,
    TEST_CLIENT_REFERRAL_SUMMARY,
    TEST_CLIENT_REFERRAL_URGENCY,
    TEST_POST_KIND,
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
async def test_consumer_post_create_form_interaction(
    origin_with_routes: str, page: Page
):
    """Submit the new-post form (client_referral kind selected); assert the
    intercepted request matches the contracted shape (POST /posts with JSON
    `{kind, summary, urgency, region}`)."""
    pact = setup_pact(
        CONSUMER_NAME_POST_CREATE,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_POST_CREATE,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{POSTS_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{POSTS_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    expected_request_body = {
        "kind": Like(TEST_POST_KIND),
        "summary": Like(TEST_CLIENT_REFERRAL_SUMMARY),
        "urgency": Like(TEST_CLIENT_REFERRAL_URGENCY),
        "region": Like(TEST_CLIENT_REFERRAL_REGION),
    }
    expected_response_body = {"id": Like(str(STUB_POST_ID))}

    (
        pact.given(PROVIDER_STATE_POSTS_ACCEPTS_CREATE)
        .upon_receiving("a request to create a post via the new-post form")
        .with_request(
            method="POST",
            path=POSTS_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"Content-Type": "application/json"},
            body=expected_response_body,
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=POSTS_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('input[type="radio"][name="kind"]')
        await page.locator(
            f'input[type="radio"][name="kind"][value="{TEST_POST_KIND}"]'
        ).check()
        await page.locator("#cr-summary").fill(TEST_CLIENT_REFERRAL_SUMMARY)
        await page.locator("#cr-urgency").select_option(TEST_CLIENT_REFERRAL_URGENCY)
        await page.locator("#cr-region").fill(TEST_CLIENT_REFERRAL_REGION)
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
