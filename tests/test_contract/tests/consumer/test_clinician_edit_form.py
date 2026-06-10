"""Consumer contract: editing the practice fields on the clinician edit form.

Verifies that the practice-fields HTMX form rendered by
`templates/clinicians/form_edit.html` (mounted via the
`clinician_edit_form` stub on the consumer server) issues a
`PATCH /clinicians/{id}` form-encoded request with the practice fields
the route expects. After #524 the practice's display name lives on
``clinician.org.name``, so the form's "what Organization?" knob is an
``org_id`` `<select>`; the form still PATCHes ``location_*`` and
session/insurance fields directly on the Clinician.

After #642 PR 1 a Clinician may hold multiple Affiliations and the
edit page surfaces them as an inline list. The top-level
`PATCH /clinicians/{id}` form is unchanged on the wire — the per-role
fields it posts (`location_*`, sessions, insurance, `sliding_scale`,
`cost`) are routed by Clinician per-role property proxies to the primary
(oldest) affiliation row. The affiliation sub-resource PATCH endpoint
(`PATCH /clinicians/{id}/clinician_affiliations/{aff_id}`) exists in the framework
but has no consumer UI today, so it is intentionally not contract-tested
here — see #647.

Sub-resource pacts (licensures, educations, certifications, plus the
inline "Add affiliation" POST) are not covered here — each would warrant
its own pair if it diverges from this shape.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CLINICIAN_EDIT_FORM_PAGE_PATH,
    CLINICIAN_NAME_CLINICIANS,
    CLINICIAN_PATCH_API_PATH,
    CLINICIAN_STATE_CLINICIAN_EXISTS_AND_OWNED,
    CONSUMER_NAME_CLINICIAN_EDIT_FORM,
    NETWORK_TIMEOUT_MS,
    PACT_PORT_CLINICIAN_EDIT,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"clinician_edit_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_clinician_edit_form_submits(
    origin_with_routes: str, page: Page
):
    """Edit a single practice field on the stubbed edit page; assert the
    intercepted PATCH matches the contracted shape."""
    pact = setup_pact(
        CONSUMER_NAME_CLINICIAN_EDIT_FORM,
        CLINICIAN_NAME_CLINICIANS,
        port=PACT_PORT_CLINICIAN_EDIT,
    )
    mock_server_uri = pact.uri
    edit_page_url = f"{origin_with_routes}{CLINICIAN_EDIT_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{CLINICIAN_PATCH_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    # The form posts every prefilled field; the test changes
    # `location_city` to confirm the PATCH wiring. Other fields keep
    # their stub values. `org_id` is the Org the stub's Clinician is
    # already attached to (its `<option selected>` in the dropdown).
    # The stub's insurance posture is self-pay-only (empty carrier list,
    # OON off, no sliding scale). The form pre-checks the "No" radio for
    # each Boolean (since `current=False`) and renders `cost` as an empty
    # text input. `in_network_carriers` is a multi-select with no current
    # selection so it doesn't appear in the encoded form body. The
    # "Clinician" fieldset holds the person-level fields (first/last
    # name and npi) and renders first, so they serialize ahead of
    # `org_id`. `first_name`, `last_name`, and `npi` are required —
    # the stub pre-fills all three so the form submits.
    expected_request_body = (
        "first_name=Jane"
        "&last_name=Doe"
        "&npi=1234567890"
        "&org_id=55555555-5555-5555-5555-555555555555"
        "&location_city=Bayside"
        "&location_state=NY"
        "&location_zip=11201"
        "&in_person_sessions=yes"
        "&virtual_sessions=please_contact"
        "&accepts_out_of_network=false"
        "&sliding_scale=false"
        "&cost="
    )

    (
        pact.given(CLINICIAN_STATE_CLINICIAN_EXISTS_AND_OWNED)
        .upon_receiving("a request to patch a clinician profile via web form")
        .with_request(
            method="PATCH",
            path=CLINICIAN_PATCH_API_PATH,
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
        api_path_to_intercept=CLINICIAN_PATCH_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="PATCH",
    )

    # The inline "Add affiliation" form below the practice section reuses
    # the same input names (`location_city`, etc.), so every locator on
    # this page must be scoped to the practice-fields form to avoid
    # strict-mode multi-match.
    practice_form = page.locator(f'form[hx-patch="{CLINICIAN_PATCH_API_PATH}"]')

    with pact:
        await page.goto(edit_page_url)
        await page.wait_for_selector('select[name="org_id"]')
        await practice_form.locator('input[name="location_city"]').fill("Bayside")
        await practice_form.locator('button[type="submit"]').click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
