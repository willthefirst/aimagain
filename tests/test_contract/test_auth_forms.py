# tests/contract/test_auth_forms.py
import string
import pytest
from playwright.async_api import Page, Route
from pact import Like


@pytest.mark.asyncio(loop_scope="session")
async def test_registration_form_fill_and_submit(pact_mock, origin: str, page: Page):
    """
    Test navigating to the registration page, filling the form,
    and submitting it correctly to the backend API (verified by Pact).
    """
    pact = pact_mock
    mock_server_uri = pact.uri
    register_page_url = f"{origin}/auth/register"
    register_api_path = "/auth/register"  # Path for the API endpoint
    full_mock_url = f"{mock_server_uri}{register_api_path}"

    # --- Define Pact Interaction ---
    expected_request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    expected_request_body = {
        "email": Like("test.user@example.com"),
        "password": Like("securepassword123"),
        "username": Like("testuser"),
    }

    (
        pact.given("User test.user@example.com does not exist")
        .upon_receiving("a request to register a new user via web form")
        .with_request(
            method="POST",
            path=register_api_path,
            headers=expected_request_headers,
            body=expected_request_body,
        )
        .will_respond_with(201)
    )

    # --- Define Playwright Interception Logic ---
    async def handle_route(route: Route):
        if route.request.method == "POST" and register_api_path in route.request.url:
            await route.continue_(
                url=full_mock_url,
                # Forward necessary headers, Content-Type is set by browser/form
                headers={
                    k: v
                    for k, v in route.request.headers.items()
                    if k.lower() != "content-length"
                },
            )
        else:
            await route.continue_()

    await page.route(f"**{register_api_path}", handle_route)

    # --- Execute Test with Pact Verification ---
    with pact:
        await page.goto(register_page_url)
        await page.wait_for_selector("#email")  # Ensure form is ready

        # Fill the form
        await page.locator("#email").fill("test.user@example.com")
        await page.locator("#password").fill("securepassword123")
        await page.locator("#username").fill("testuser")

        # Submit the form (triggers interception)
        await page.locator("input[type='submit']").click()

        # Wait for network request processing
        await page.wait_for_timeout(500)

    # Pact verification happens automatically on context exit.
