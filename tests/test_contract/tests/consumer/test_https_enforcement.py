# tests/test_contract/tests/consumer/test_https_enforcement.py
import pytest
from playwright.async_api import Page

# Test Constants
HTTPS_TEST_PATHS = [
    "/conversations/new",
    "/auth/login",
    "/auth/register",
]


@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.consumer
@pytest.mark.https
async def test_forms_use_https_when_force_https_enabled(
    origin_with_routes: str, page: Page
):
    """
    Test that all forms use HTTPS URLs when FORCE_HTTPS is enabled.

    This test simulates a production environment where forms should
    submit to HTTPS endpoints for security.
    """
    origin = origin_with_routes

    # Test conversation creation form
    new_conversation_url = f"{origin}/conversations/new"
    await page.goto(new_conversation_url)

    # Get the form action URL
    form_action = await page.get_attribute(
        "form[name='create-conversation-form']", "action"
    )

    # Assert that the form action uses HTTPS
    assert form_action is not None, "Form action should not be None"
    assert form_action.startswith(
        "https://"
    ), f"Form action should use HTTPS, got: {form_action}"


@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.consumer
@pytest.mark.https
async def test_links_use_https_when_force_https_enabled(
    origin_with_routes: str, page: Page
):
    """
    Test that navigation links use HTTPS URLs when FORCE_HTTPS is enabled.
    """
    origin = origin_with_routes

    # Test conversation creation page
    new_conversation_url = f"{origin}/conversations/new"
    await page.goto(new_conversation_url)

    # Get the "Back to conversations" link
    back_link = await page.get_attribute("a[href*='conversations']", "href")

    # Assert that the link uses HTTPS
    assert back_link is not None, "Back link should not be None"
    assert back_link.startswith(
        "https://"
    ), f"Back link should use HTTPS, got: {back_link}"


@pytest.mark.parametrize(
    "origin_with_routes", [{"conversations": True, "auth_pages": True}], indirect=True
)
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.consumer
@pytest.mark.https
async def test_https_with_forwarded_proto_header(origin_with_routes: str, page: Page):
    """
    Test that forms use HTTPS when X-Forwarded-Proto header indicates HTTPS,
    simulating a reverse proxy environment like Railway.
    """
    origin = origin_with_routes

    # Set extra HTTP headers to simulate reverse proxy
    await page.set_extra_http_headers(
        {"X-Forwarded-Proto": "https", "X-Forwarded-Host": "myapp.railway.app"}
    )

    # Test conversation creation form
    new_conversation_url = f"{origin}/conversations/new"
    await page.goto(new_conversation_url)

    # Get the form action URL
    form_action = await page.get_attribute(
        "form[name='create-conversation-form']", "action"
    )

    # Assert that the form action uses HTTPS due to the forwarded proto header
    assert form_action is not None, "Form action should not be None"
    assert form_action.startswith(
        "https://"
    ), f"Form action should use HTTPS with X-Forwarded-Proto, got: {form_action}"
