"""Consumer contract: editing the practice fields on the provider edit form.

Verifies that the practice-fields HTMX form rendered by
`templates/providers/edit.html` (mounted via the
`provider_edit_form` stub on the consumer server) issues a
`PATCH /providers/{id}` form-encoded request with at least the
`practice_name` field. The contract surface is the form wiring (method,
path, Content-Type, field name); the response on success is a 200 JSON
with `HX-Redirect` to the same edit page so the user lands back on it.

Sub-resource pacts (licensures, educations, certifications) are not
covered here — each would warrant its own pair if it diverges from this
shape.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_PROVIDER_EDIT_FORM,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_PROVIDER_EDIT,
    PROVIDER_EDIT_FORM_PAGE_PATH,
    PROVIDER_NAME_PROVIDERS,
    PROVIDER_PATCH_API_PATH,
    PROVIDER_STATE_PROVIDER_EXISTS_AND_OWNED,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"provider_edit_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_provider_edit_form_submits(origin_with_routes: str, page: Page):
    """Edit a single practice field on the stubbed edit page; assert the
    intercepted PATCH matches the contracted shape."""
    pact = setup_pact(
        CONSUMER_NAME_PROVIDER_EDIT_FORM,
        PROVIDER_NAME_PROVIDERS,
        port=PACT_PORT_PROVIDER_EDIT,
    )
    mock_server_uri = pact.uri
    edit_page_url = f"{origin_with_routes}{PROVIDER_EDIT_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{PROVIDER_PATCH_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    # The form posts every prefilled field; the practice_name override is
    # what the test changes. Other fields keep their stub values from the
    # consumer-server stub. The body shape is the contract; concrete values
    # are ergonomic for the verifier.
    expected_request_body = (
        "practice_name=Bayside+Counseling"
        "&location_city=Brooklyn"
        "&location_state=NY"
        "&location_zip=11201"
        "&in_person_sessions=yes"
        "&virtual_sessions=please_contact"
    )

    (
        pact.given(PROVIDER_STATE_PROVIDER_EXISTS_AND_OWNED)
        .upon_receiving("a request to patch a provider profile via web form")
        .with_request(
            method="PATCH",
            path=PROVIDER_PATCH_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=200,
            headers={"HX-Redirect": Like("/providers/abc/form")},
            body={"id": Like("44444444-4444-4444-4444-444444444444")},
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=PROVIDER_PATCH_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="PATCH",
    )

    with pact:
        await page.goto(edit_page_url)
        await page.wait_for_selector('input[name="practice_name"]')
        await page.locator('input[name="practice_name"]').fill("Bayside Counseling")
        # Submit the practice-fields form (the first one on the page).
        await page.locator(
            f'form[hx-patch="{PROVIDER_PATCH_API_PATH}"] input[type="submit"]'
        ).click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
