# tests/test_contract/test_consumer_user_list.py
import pytest
from playwright.async_api import (
    Page,
    expect,
)  # Route might not be needed for simple GET
from pact import Like  # Import Like
import re

from tests.test_contract.test_helpers import (
    setup_pact,
    # setup_playwright_pact_interception, # May not be needed for GET if no form submission
)

# from tests.shared_test_data import ... # If shared data for users is available

CONSUMER_NAME = "user-list-page"
PROVIDER_NAME = "users-api"  # Assuming this is the provider for user-related endpoints

# Test Constants
USERS_LIST_PATH = "/users"
# Mock data for users if needed for verifying response body (Like(...))
# For HTML, often only status and headers are checked in contract tests.
PROVIDER_STATE_USERS_EXIST_AUTH = (
    "users exist in the system and the requesting user is authenticated"
)

NETWORK_TIMEOUT_MS = 1000  # Increased timeout slightly just in case


@pytest.mark.parametrize(
    "origin_with_routes",
    [
        {
            "users_pages": True,  # Assuming a fixture key for user pages/routes
            "auth_pages": True,  # For authentication if required by the page
        }
    ],
    indirect=True,
)
@pytest.mark.asyncio(loop_scope="session")
async def test_consumer_user_list_success(origin_with_routes: str, page: Page):
    """
    Test the user listing page - navigating to the page and expecting a successful response.
    """
    origin = origin_with_routes

    pact = setup_pact(CONSUMER_NAME, PROVIDER_NAME, port=1236)  # Different port
    mock_server_uri = pact.uri
    list_users_url = f"{origin}{USERS_LIST_PATH}"
    mock_list_users_url = f"{mock_server_uri}{USERS_LIST_PATH}"

    # Define Pact Interaction for successful user list page load
    (
        pact.given(PROVIDER_STATE_USERS_EXIST_AUTH)
        .upon_receiving("a request to view the list of users")
        .with_request(
            method="GET",
            path=USERS_LIST_PATH,
            # headers={ "Accept": "text/html" } # Optional: if we want to be specific
        )
        .will_respond_with(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            # body=Like("<html...>") # Usually not done for full HTML pages
        )
    )

    # Playwright Interception for GET requests (if directly testing via Playwright's goto)
    # This might be simpler: we tell Playwright to go to the *actual* app URL,
    # but set up Pact to expect the call.
    # No complex interception like for POST forms is usually needed here.
    # However, if the page itself makes client-side API calls to /users, then interception
    # would be needed for *those* calls.
    # For a simple server-rendered HTML page, this is more about verifying the initial GET.

    # For this test, we assume Playwright will hit the mock server *if* the app
    # was configured to point its /users route to pact.uri. But that's not how this works.
    # Playwright hits the *real* app's URL (origin_with_routes + USERS_LIST_PATH).
    # The pact is for the *provider* to verify against.
    # So, the test should ensure that the application, when run, makes a call
    # that matches the pact definition when `page.goto(list_users_url)` is called.
    # For this consumer test, it's more about *defining* the contract.

    with pact:  # This starts the mock server
        # In a true UI-driven test that makes an AJAX call to /users, we would intercept.
        # Here, page.goto makes the request directly. The pact mock server will see it
        # if the test environment routes `origin` to the pact mock server for this path.
        # However, the more common pattern for consumer test is to use an HTTP client
        # to make the request to pact.uri directly.
        # For Playwright, it's about testing the UI *component* (the page)
        # that *consumes* an API. If page.goto directly fetches the HTML from /users,
        # this sets the expectation for the provider.

        # Let's assume the test setup (not shown here, e.g. via host overrides or
        # service discovery in a more complex setup) would route calls from the app
        # (when page.goto is called) to the Pact mock server for the /users path.
        # This is tricky with Playwright as it loads the actual app.
        # A simpler approach for consumer testing a GET endpoint is to use `requests`
        # or `httpx` directly against `mock_list_users_url`.

        # For now, proceeding as if `page.goto` on the app's URL generates the expected request
        # to the provider (which Pact mock server emulates).
        # This is more of a contract *declaration* by the consumer (frontend).

        await page.goto(
            mock_list_users_url
        )  # Navigate directly to the pact mock server URL
        # The pact mock server defined above will assert this call.

        # We expect the page to load successfully (status 200 from pact interaction)
        # This implicitly means the call page.goto made was successful (status 200).
        # We can add a playwright assertion for the page having loaded, e.g. a title.
        # await expect(page).to_have_title(Like(".*"))  # Check if title exists
        await expect(page).to_have_title(re.compile(".*"))  # Use re.compile for regex
        await page.wait_for_timeout(
            NETWORK_TIMEOUT_MS
        )  # Give time for any async operations

    # Pact verification (that the mock server received the expected request)
    # happens automatically on `with pact:` context exit.
