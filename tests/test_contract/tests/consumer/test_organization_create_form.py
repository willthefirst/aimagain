"""Consumer contract: filling and submitting the organization create form.

Verifies that the HTMX-decorated form rendered by
`templates/organizations/form_new.html` (mounted via the
`organization_create_form` stub on the consumer server) issues a
`POST /organizations` form-encoded request with the field names and
shapes the route's `OrganizationCreate` schema expects.

Pinning the **blank `parent_org_id=`** field in the request body is
deliberate: it's exactly the wire shape that 422'd in prod (#550, fixed
by `OptionalUuid` on `OrganizationCreate.parent_org_id`). Keeping it in
the pact stops a future schema change from regressing the create flow
without a contract bump.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_ORGANIZATION_CREATE_FORM,
    NETWORK_TIMEOUT_MS,
    ORGANIZATION_CREATE_API_PATH,
    ORGANIZATION_CREATE_FORM_PAGE_PATH,
    PACT_PORT_ORGANIZATION_CREATE,
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
    """Fill the create form on the stubbed page; assert the intercepted
    request matches the contracted shape — including a blank
    `parent_org_id` (the #550 regression)."""
    pact = setup_pact(
        CONSUMER_NAME_ORGANIZATION_CREATE_FORM,
        PROVIDER_NAME_ORGANIZATIONS,
        port=PACT_PORT_ORGANIZATION_CREATE,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{ORGANIZATION_CREATE_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{ORGANIZATION_CREATE_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    # Browser serializes inputs in DOM order: name, type, npi (optional,
    # left blank here), parent_org_id. The blank `parent_org_id=` pins the
    # #550 regression; the blank `npi=` pins that the optional NPI field
    # serializes empty without 422'ing (#1166).
    expected_request_body = (
        "name=Acme+Counseling" "&type=clinic" "&npi=" "&parent_org_id="
    )

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
        await page.locator('select[name="type"]').select_option("clinic")
        # parent_org_id intentionally left blank — pins #550.
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
