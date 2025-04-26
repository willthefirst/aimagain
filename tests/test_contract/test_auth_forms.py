# tests/contract/test_auth_forms.py
import string
import pytest
from playwright.async_api import Page, Route
from pact import Like  # Import necessary pact objects


@pytest.mark.asyncio(loop_scope="session")
async def test_registration_form_fill(origin: string, page: Page):
    """Test navigating to the registration page and filling the form."""
    register_url = f"{origin}/auth/register"
    await page.goto(register_url)

    await page.locator("#email").fill("test.user@example.com")
    await page.locator("#password").fill("securepassword123")
    await page.locator("#username").fill("testuser")


# Intentionally leaving the final comment about form submission/Pact
# as it seems like a relevant note for future work.


# --- New Pact Consumer Test ---
@pytest.mark.asyncio(loop_scope="session")
async def test_registration_form_submission(pact_mock, origin: str, page: Page):
    """
    Test that submitting the registration form sends the correct
    request to the backend API (as verified by Pact).
    """
    pact = pact_mock  # Get the pact instance from the fixture
    mock_server_uri = pact.uri
    # Path as defined in the FastAPI router (app.api.routes.auth_pages)
    register_api_path = "/auth/register"
    full_mock_url = f"{mock_server_uri}{register_api_path}"

    # --- 1. Define Pact Interaction ---
    # Standard HTML forms submit urlencoded data by default
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    # Pact requires urlencoded body to be defined.
    # We use 'Like' here assuming pact-python can handle dictionary-like
    # structure for urlencoded matching. Needs verification/adjustment if not.
    expected_request_body = {
        "email": Like("test.user@example.com"),
        "password": Like("securepassword123"),
        "username": Like("testuser"),
    }

    (
        pact.given("User test.user@example.com does not exist")  # Provider state
        .upon_receiving("a request to register a new user via web form")
        .with_request(
            method="POST",
            path=register_api_path,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(201)  # Expecting 201 Created on success
    )

    # --- 2. Define and Apply Playwright Interception Logic Inline ---
    async def handle_route(route: Route):
        # Intercept the specific POST request to the original backend path
        if route.request.method == "POST" and register_api_path in route.request.url:
            print(
                f"Intercepted POST to {route.request.url}, redirecting to {full_mock_url}"
            )
            # Redirect to the Pact mock server
            # Preserve original request data (method, headers, postData)
            await route.continue_(url=full_mock_url)
        else:
            # Let other requests (e.g., GET for the page itself) pass through
            await route.continue_()

    # Apply the handler to the specific API path
    # Using `**` ensures it matches the full URL containing the path
    await page.route(f"**{register_api_path}", handle_route)

    # --- 3. Execute Test with Pact Verification ---
    with pact:  # Start interaction context & enable verification on exit
        # Navigate to the registration page served by the fixture's test server
        # NOTE: This currently hits the live endpoint in the test server.
        # Future step per contract_testing.md is to serve static HTML.
        print(f"Navigating to {origin}/auth/register")
        register_page_url = f"{origin}/auth/register"
        await page.goto(register_page_url)
        # Wait for form elements to be ready if necessary
        await page.wait_for_selector("#email")
        print("Form elements ready")

        # Fill the form
        await page.locator("#email").fill("test.user@example.com")
        await page.locator("#password").fill("securepassword123")
        await page.locator("#username").fill("testuser")

        # Submit the form - this triggers the intercepted POST request
        # Ensure the selector matches your actual submit button
        await page.locator("input[type='submit']").click()
        print("Form submitted")
        # Add a small wait to ensure the network request is processed by Pact
        # Adjust time if needed, or use a more robust wait like waiting for
        # a specific network response or UI change if applicable.
        await page.wait_for_timeout(500)

    # Pact verification happens automatically when 'with pact:' block exits.
    # If the request didn't match the expectation, an error will be raised here.
    # If successful, the pact file in '../pacts/' is created/updated.
