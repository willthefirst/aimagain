"""Consumer contract: editing the person-level fields on the clinician edit form.

Verifies that the HTMX form rendered by
`templates/clinicians/form_edit.html` (mounted via the
`clinician_edit_form` stub on the consumer server) issues a
`PATCH /clinicians/{id}` form-encoded request with the person-level
fields the route expects (`first_name`, `last_name`, `npi`).

After #1308, practice posture (location, availability, insurance,
cost, `org_id`) moved off this form onto each `ClinicianAffiliation`,
because posture genuinely varies per (clinician × context) — same
person can hold telehealth-only solo + in-person-Aetna-paneled-group
simultaneously. The clinician form is now person-level only.

Sub-resource pacts (licensures, educations, certifications, plus the
inline "Add affiliation" POST and the per-affiliation PATCH) are not
covered here — each would warrant its own pair if it diverges from
this shape.
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
    )
    mock_server_uri = pact.uri
    edit_page_url = f"{origin_with_routes}{CLINICIAN_EDIT_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{CLINICIAN_PATCH_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    # The form posts only the person-level prefilled fields after #1308;
    # the test changes `first_name` to confirm the PATCH wiring. The
    # stub pre-fills first/last/npi so the form submits.
    expected_request_body = "first_name=Janet&last_name=Doe&npi=1234567890"

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

    # The inline "Add affiliation" form below reuses some input names
    # (org_id, location_city, etc.), but the clinician PATCH form itself
    # only carries person-level inputs (first/last/npi) — scope locators
    # to the PATCH form to avoid strict-mode multi-match anyway.
    person_form = page.locator(f'form[hx-patch="{CLINICIAN_PATCH_API_PATH}"]')

    with pact:
        await page.goto(edit_page_url)
        await person_form.locator('input[name="first_name"]').wait_for()
        await person_form.locator('input[name="first_name"]').fill("Janet")
        await person_form.locator('button[type="submit"]').click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
