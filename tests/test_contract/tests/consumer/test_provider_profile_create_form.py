"""Consumer contract: filling and submitting the provider-profile create form.

Verifies that the HTMX-decorated form rendered by
`templates/provider_profiles/new.html` (mounted via the
`provider_profile_create_form` stub on the consumer server) issues a
`POST /providers` form-encoded request with the practice and
availability fields the route's `ProviderCreate` schema expects.
The contract surface is the form wiring (method, path, Content-Type,
field names) — the response on success is a 201 with `HX-Redirect` to
the new profile.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_PROVIDER_PROFILE_CREATE_FORM,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_PROVIDER_PROFILE_CREATE,
    PROVIDER_NAME_PROVIDER_PROFILES,
    PROVIDER_PROFILE_CREATE_API_PATH,
    PROVIDER_PROFILE_CREATE_FORM_PAGE_PATH,
    PROVIDER_STATE_USER_CAN_CREATE_PROFILE,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"provider_profile_create_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_provider_profile_create_form_submits(
    origin_with_routes: str, page: Page
):
    """Fill the create form on the stubbed page; assert the intercepted
    request matches the contracted shape."""
    pact = setup_pact(
        CONSUMER_NAME_PROVIDER_PROFILE_CREATE_FORM,
        PROVIDER_NAME_PROVIDER_PROFILES,
        port=PACT_PORT_PROVIDER_PROFILE_CREATE,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{PROVIDER_PROFILE_CREATE_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{PROVIDER_PROFILE_CREATE_API_PATH}"

    # Browser form submit sets Content-Type to
    # `application/x-www-form-urlencoded; charset=UTF-8`; pact-ruby's header
    # matcher does substring match unless the value is wrapped in `Like`.
    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    expected_request_body = (
        "practice_name=Acme+Counseling"
        "&location_city=Brooklyn"
        "&location_state=NY"
        "&location_zip=11201"
        "&in_person_sessions=yes"
        "&virtual_sessions=please_contact"
    )

    (
        pact.given(PROVIDER_STATE_USER_CAN_CREATE_PROFILE)
        .upon_receiving("a request to create a provider profile via web form")
        .with_request(
            method="POST",
            path=PROVIDER_PROFILE_CREATE_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"HX-Redirect": Like("/providers/abc")},
            body={"id": Like("33333333-3333-3333-3333-333333333333")},
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=PROVIDER_PROFILE_CREATE_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('input[name="practice_name"]')
        await page.locator('input[name="practice_name"]').fill("Acme Counseling")
        await page.locator('input[name="location_city"]').fill("Brooklyn")
        await page.locator('select[name="location_state"]').select_option("NY")
        await page.locator('input[name="location_zip"]').fill("11201")
        await page.locator('select[name="in_person_sessions"]').select_option("yes")
        await page.locator('select[name="virtual_sessions"]').select_option(
            "please_contact"
        )
        await page.locator("input[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
