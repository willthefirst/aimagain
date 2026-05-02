"""Consumer contract: filling and submitting the client_referral edit-post form.

Verifies that the form rendered by `templates/posts/edit_client_referral.html`
(mounted via the `posts_pages` flag on the consumer server) issues
`PATCH /posts/{id}` with a JSON body matching `ClientReferralUpdate` for
the multi-section intake form. The contract surface is the edit template
and the route's PATCH request shape.

Only `client_referral` has an edit page (provider_availability has no
editable fields yet) — extend this pair when that changes.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_POST_EDIT,
    EDITED_CLIENT_REFERRAL_DESCRIPTION,
    EDITED_CLIENT_REFERRAL_INSURANCE,
    EDITED_CLIENT_REFERRAL_LOCATION_CITY,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_POST_EDIT,
    POST_EDIT_API_PATH,
    POST_EDIT_PAGE_PATH,
    PROVIDER_NAME_POSTS,
    PROVIDER_STATE_POST_EXISTS_AND_OWNED,
    STUB_POST_ID,
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
async def test_consumer_post_edit_form_interaction(origin_with_routes: str, page: Page):
    pact = setup_pact(
        CONSUMER_NAME_POST_EDIT,
        PROVIDER_NAME_POSTS,
        port=PACT_PORT_POST_EDIT,
    )
    mock_server_uri = pact.uri
    edit_page_url = f"{origin_with_routes}{POST_EDIT_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{POST_EDIT_API_PATH}"

    expected_request_headers = {"Content-Type": "application/json"}
    # The edit form submits *every* field (the entire client_referral cluster
    # is rendered with current values); pact `Like` matchers keep the
    # contract focused on the shape rather than specific values.
    expected_request_body = {
        "kind": Like(TEST_POST_KIND),
        "location_city": Like(EDITED_CLIENT_REFERRAL_LOCATION_CITY),
        "location_state": Like("MA"),
        "location_zip": Like("01060"),
        "location_in_person": Like("yes"),
        "location_virtual": Like("please_contact"),
        "client_dem_ages": Like("adults_25_64"),
        "language_preferred": Like("no"),
        "description": Like(EDITED_CLIENT_REFERRAL_DESCRIPTION),
        "services_psychotherapy_modality": Like("DBT"),
        "insurance": Like(EDITED_CLIENT_REFERRAL_INSURANCE),
    }
    expected_response_body = {"id": Like(str(STUB_POST_ID))}

    (
        pact.given(PROVIDER_STATE_POST_EXISTS_AND_OWNED)
        .upon_receiving(
            "a request to edit a client_referral post via the edit-post form"
        )
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
        await page.wait_for_selector("#cr-description")
        await page.locator("#cr-location-city").fill(
            EDITED_CLIENT_REFERRAL_LOCATION_CITY
        )
        await page.locator("#cr-description").fill(EDITED_CLIENT_REFERRAL_DESCRIPTION)
        await page.locator("#cr-insurance").select_option(
            EDITED_CLIENT_REFERRAL_INSURANCE
        )
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)
