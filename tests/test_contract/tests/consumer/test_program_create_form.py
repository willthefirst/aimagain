"""Consumer contract: filling and submitting the program create form.

Verifies that the HTMX-decorated form rendered by
`templates/programs/form_new.html` (mounted via the `program_create_form`
stub on the consumer server) issues a `POST /programs` form-encoded
request with the field names and shapes the route's `ProgramCreate`
schema expects. The form's `org_id` dropdown is populated by
`program_form_extras` in production (scoped to the user's owned Orgs);
the stub seeds one Org so the pact body is deterministic.

`description`, `start_date`, and `end_date` are all left **blank** —
the browser submits ``description=&start_date=&end_date=`` and the
``WirePayload._coerce_blank_strings_on_nullable_scalars`` model
validator collapses each to ``None`` before per-field validation runs.
Pinning the blank wire shape is the whole point — this is the shape
the prod form actually produces, and #551 (the systemic fix) made it
accepted.
"""

import pytest
from pact import Like
from playwright.async_api import Page

from tests.test_contract.constants import (
    CONSUMER_NAME_PROGRAM_CREATE_FORM,
    NETWORK_TIMEOUT_MS,
    PROGRAM_CREATE_API_PATH,
    PROGRAM_CREATE_FORM_PAGE_PATH,
    PROVIDER_NAME_PROGRAMS,
    PROVIDER_STATE_USER_CAN_CREATE_PROGRAM,
    STUB_PROGRAM_FORM_ORG_ID,
)
from tests.test_contract.tests.shared.helpers import (
    setup_pact,
    setup_playwright_pact_interception,
)


@pytest.mark.parametrize(
    "origin_with_routes",
    [{"program_create_form": True, "auth_pages": False}],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_program_create_form_submits(
    origin_with_routes: str, page: Page
):
    """Fill the create form on the stubbed page; assert the intercepted
    request matches the contracted shape — including blank optional
    text/date inputs (the #551 regression)."""
    pact = setup_pact(
        CONSUMER_NAME_PROGRAM_CREATE_FORM,
        PROVIDER_NAME_PROGRAMS,
    )
    mock_server_uri = pact.uri
    form_page_url = f"{origin_with_routes}{PROGRAM_CREATE_FORM_PAGE_PATH}"
    full_mock_url = f"{mock_server_uri}{PROGRAM_CREATE_API_PATH}"

    expected_request_headers = {
        "Content-Type": Like("application/x-www-form-urlencoded")
    }
    # DOM-order field serialization. Blank optional inputs serialize
    # as `<name>=`; the `accepting_referrals` checkbox is pre-checked
    # by the template (`current=true`). `checkbox_field` emits a
    # sibling `<input type="hidden" value="false">` before the
    # checkbox so default-true booleans round-trip — checked submits
    # both, the parser collapses to the last value (see
    # `src/framework/http/forms.py`).
    # The "Services offered" / "Clients served" multi-checkbox groups
    # serialize *only* their checked options — none are checked on this
    # blank submission, so they emit zero key=value pairs. The "How to
    # refer" cluster's `website` and `referral_instructions` are blank
    # text/textarea inputs, so they each serialize as `<name>=` — same
    # shape as `description=` above. `StrippedOptionalText` collapses
    # `''` to `None` server-side.
    expected_request_body = (
        f"org_id={STUB_PROGRAM_FORM_ORG_ID}"
        "&name=Intensive+Outpatient"
        "&description="
        "&state_preference=NY"
        "&start_date="
        "&end_date="
        "&accepting_referrals=false"
        "&accepting_referrals=true"
        "&website="
        "&referral_instructions="
    )

    (
        pact.given(PROVIDER_STATE_USER_CAN_CREATE_PROGRAM)
        .upon_receiving("a request to create a program via web form")
        .with_request(
            method="POST",
            path=PROGRAM_CREATE_API_PATH,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(
            status=201,
            headers={"HX-Redirect": Like("/programs/abc/form")},
            body={"id": Like("99999999-9999-9999-9999-999999999999")},
        )
    )

    await setup_playwright_pact_interception(
        page=page,
        api_path_to_intercept=PROGRAM_CREATE_API_PATH,
        mock_pact_url=full_mock_url,
        http_method="POST",
    )

    with pact:
        await page.goto(form_page_url)
        await page.wait_for_selector('select[name="org_id"]')
        await page.locator('select[name="org_id"]').select_option(
            str(STUB_PROGRAM_FORM_ORG_ID)
        )
        await page.locator('input[name="name"]').fill("Intensive Outpatient")
        await page.locator('select[name="state_preference"]').select_option("NY")
        # description / start_date / end_date intentionally left blank
        # — pins the #551 regression class.
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(NETWORK_TIMEOUT_MS)

    # Pact verification happens automatically on context exit.
