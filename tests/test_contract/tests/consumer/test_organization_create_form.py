"""Consumer contract: filling and submitting the organization create form.

Verifies that the HTMX-decorated form rendered by
`templates/organizations/form_new.html` (mounted via the
`organization_create_form` stub on the consumer server) issues a
`POST /organizations` form-encoded request with the field names and
shapes the route's `OrganizationCreate` schema expects.

The create form is intentionally minimal: just `name` and `npi`.
Anything else — parent linkage, demo flag, etc. — is added on the edit
page once the row exists.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_ORGANIZATION_CREATE_FORM,
    NETWORK_TIMEOUT_MS,
    ORGANIZATION_CREATE_API_PATH,
    ORGANIZATION_CREATE_FORM_PAGE_PATH,
    PROVIDER_NAME_ORGANIZATIONS,
    PROVIDER_STATE_USER_CAN_CREATE_ORGANIZATION,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"organization_create_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_organization_create_form_submits(
    origin_with_routes: str, page: Page
):
    """Fill the minimal create form on the stubbed page; assert the
    intercepted request matches the contracted shape — `name` + `npi`."""
    pact = setup_pact(
        CONSUMER_NAME_ORGANIZATION_CREATE_FORM,
        PROVIDER_NAME_ORGANIZATIONS,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{ORGANIZATION_CREATE_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{ORGANIZATION_CREATE_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    expected_request_body = "name=Acme+Counseling&npi=1234567890"

    (
        pact.given(PROVIDER_STATE_USER_CAN_CREATE_ORGANIZATION)
        .upon_receiving("a request to create an organization via web form")
        .with_request(
            method="POST",
            path=ORGANIZATION_CREATE_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"HX-Redirect": Like("/organizations/abc/form")},
            body={"id": Like("88888888-8888-8888-8888-888888888888")},
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=ORGANIZATION_CREATE_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('input[name="name"]')
        await page.locator('input[name="name"]').fill("Acme Counseling")
        await page.locator('input[name="npi"]').fill("1234567890")
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
