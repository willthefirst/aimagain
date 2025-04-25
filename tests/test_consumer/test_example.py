import re
from playwright.sync_api import Page, expect, sync_playwright
import atexit
import unittest

from pact import Consumer, Provider

pact = Consumer("RegisterConsumer").has_pact_with(Provider("RegisterProvider"))
pact.start_service()
atexit.register(pact.stop_service)


class RegisterClient:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def test_register_form_submit(self, page: Page):
        page.goto(f"{self.base_url}/auth/register")

        # Fill in the register form
        page.get_by_label("Email").fill("test@test.com")
        page.get_by_label("Username").fill("testuser")
        page.get_by_label("Password").fill("testpassword")

        # Submit the register form
        page.get_by_role("button", name="Register").click()

        # Intercept the request
        response = page.wait_for_response(
            lambda response: response.url.endswith("/auth/register/")
            and response.request.method == "POST"
            and response.status == 201
            and response.headers["content-type"] == "application/json"
        )
        return response.json()


class Register(unittest.TestCase):
    def test_register(self) -> None:
        expected = {
            "email": "test@test.com",
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
        }

        (
            pact.given("Somebody wants to register")
            .upon_receiving("a request for to register a new user")
            .with_request("post", "/auth/register/")
            .will_respond_with(
                201, headers={"content-type": "application/json"}, body=expected
            )
        )

        client = RegisterClient(pact.uri)

        with pact:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                try:
                    result = client.test_register_form_submit(page=page)
                    self.assertEqual(result, expected)
                finally:
                    page.close()
                    browser.close()
