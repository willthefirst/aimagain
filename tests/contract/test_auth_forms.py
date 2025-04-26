# tests/contract/test_auth_forms.py
import string
import pytest
import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page


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
