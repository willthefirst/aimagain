import re
from playwright.sync_api import Page, expect


def test_register_form_submit(page: Page):
    page.goto("http://127.0.0.1:8000/auth/register")

    page.get_by_label("Email").fill("test@test.com")
    page.get_by_label("Username").fill("testuser")
    page.get_by_label("Password").fill("testpassword")

    page.get_by_role("button", name="Register").click()
