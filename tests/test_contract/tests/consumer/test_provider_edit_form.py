"""Consumer contract: editing the practice fields on the provider edit form.

Verifies that the practice-fields HTMX form rendered by
`templates/providers/form_edit.html` (mounted via the
`provider_edit_form` stub on the consumer server) issues a
`PATCH /clinicians/{id}` form-encoded request with the practice fields
the route expects. After #524 the practice's display name lives on
``provider.org.name``, so the form's "what Organization?" knob is an
``org_id`` `<select>`; the form still PATCHes ``location_*`` and
session/insurance fields directly on the Provider.

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


@pytest.mark.skip(
    reason=(
        "Pact stale after #642 PR 1: per-role fields (`location_*`, sessions, "
        "insurance, sliding_scale, cost) moved out of the top-level provider "
        "PATCH form into inline affiliation rows. The wire endpoint shifted "
        "from `PATCH /clinicians/{id}` to `PATCH /clinicians/{id}/affiliations/"
        "{affiliation_id}` and the encoded body shape changed. Tracked in "
        "#647 — rewrite the pact pair for the affiliation PATCH surface, or "
        "drop it if affiliation editing doesn't need a separate consumer "
        "contract."
    )
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
    # The form posts every prefilled field; the test changes
    # `location_city` to confirm the PATCH wiring. Other fields keep
    # their stub values. `org_id` is the Org the stub's Provider is
    # already attached to (its `<option selected>` in the dropdown).
    # The stub's insurance posture is self-pay-only (empty carrier list,
    # OON off, no sliding scale). The form pre-checks the "No" radio for
    # each Boolean (since `current=False`) and renders `cost` as an empty
    # text input. `in_network_carriers` is a multi-select with no current
    # selection so it doesn't appear in the encoded form body. `npi` is
    # an empty optional text input on the stub (#525), so it serializes
    # as `npi=` right after `location_zip`.
    expected_request_body = (
        "org_id=55555555-5555-5555-5555-555555555555"
        "&location_city=Bayside"
        "&location_state=NY"
        "&location_zip=11201"
        "&npi="
        "&in_person_sessions=yes"
        "&virtual_sessions=please_contact"
        "&accepts_out_of_network=false"
        "&sliding_scale=false"
        "&cost="
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
            headers={"HX-Redirect": Like("/clinicians/abc/form")},
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
        await page.wait_for_selector('select[name="org_id"]')
        await page.locator('input[name="location_city"]').fill("Bayside")
        # Submit the practice-fields form (the first one on the page).
        await page.locator(
            f'form[hx-patch="{PROVIDER_PATCH_API_PATH}"] button[type="submit"]'
        ).click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
