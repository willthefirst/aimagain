"""Consumer contract: filling and submitting the clinician create form.

Verifies that the HTMX-decorated form rendered by
`templates/clinicians/form_new.html` (mounted via the
`clinician_create_form` stub on the consumer server) issues a
`POST /clinicians` form-encoded request with the field names and
shapes the route's `ClinicianCreate` schema expects.

The create form is intentionally minimal: just `first_name`,
`last_name`, and `npi`. Affiliation, location, availability, and
insurance fields are added later via the affiliation sub-resource on
the edit page.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CLINICIAN_CREATE_API_PATH,
    CLINICIAN_CREATE_FORM_PAGE_PATH,
    CLINICIAN_NAME_CLINICIANS,
    CLINICIAN_STATE_USER_CAN_CREATE_CLINICIAN,
    CONSUMER_NAME_CLINICIAN_CREATE_FORM,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_CLINICIAN_CREATE,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"clinician_create_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_clinician_create_form_submits(
    origin_with_routes: str, page: Page
):
    """Fill the minimal create form on the stubbed page; assert the
    intercepted request matches the contracted shape — `first_name`,
    `last_name`, `npi` only."""
    pact = setup_pact(
        CONSUMER_NAME_CLINICIAN_CREATE_FORM,
        CLINICIAN_NAME_CLINICIANS,
        port=PACT_PORT_CLINICIAN_CREATE,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{CLINICIAN_CREATE_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{CLINICIAN_CREATE_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    expected_request_body = "first_name=Jane&last_name=Doe&npi=1234567890"

    (
        pact.given(CLINICIAN_STATE_USER_CAN_CREATE_CLINICIAN)
        .upon_receiving("a request to create a clinician profile via web form")
        .with_request(
            method="POST",
            path=CLINICIAN_CREATE_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"HX-Redirect": Like("/clinicians/abc")},
            body={"id": Like("33333333-3333-3333-3333-333333333333")},
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=CLINICIAN_CREATE_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('input[name="first_name"]')
        await page.locator('input[name="first_name"]').fill("Jane")
        await page.locator('input[name="last_name"]').fill("Doe")
        await page.locator('input[name="npi"]').fill("1234567890")
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
