# tests/contract/test_auth_forms.py
import pytest
import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page

# We only need fastapi_server and page fixtures for this test


@pytest.mark.asyncio(loop_scope="session")
async def test_registration_form_fill(fastapi_server, page: Page):
    """Test navigating to the registration page and filling the form (headful)."""
    register_url = f"{fastapi_server}/auth/register"
    print(f"Navigating to {register_url}")

    try:
        # Revert to default wait_until ('load') but keep timeout
        await page.goto(register_url)  # Increased timeout slightly
        print("Navigation successful (load event).")
    except PlaywrightTimeoutError:
        pytest.fail(
            f"Timeout error: Navigation to {register_url} (waiting for load event) took too long."
        )
    except Exception as e:
        pytest.fail(f"Error during navigation to {register_url}: {e}")

    print("Attempting to fill email field...")
    await page.locator("#email").fill("test.user@example.com")
    print("Email field filled.")

    print("Attempting to fill password field...")
    await page.locator("#password").fill("securepassword123")
    print("Password field filled.")

    # Also fill the username field as it seems to be required by the form
    print("Attempting to fill username field...")
    await page.locator("#username").fill("testuser")
    print("Username field filled.")

    # Pause for a few seconds so you can see the filled form in headful mode
    print("Form filled. Pausing for 3 seconds...")
    await page.wait_for_timeout(3000)

    print("Pause finished. Test successfully completed.")


# Note: This test doesn't submit the form or involve Pact yet.
