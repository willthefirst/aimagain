import pytest
from httpx import AsyncClient
from selectolax.parser import HTMLParser

pytestmark = pytest.mark.asyncio


async def test_get_new_conversation_form_success(authenticated_client: AsyncClient):
    """Test GET /conversations/new returns the form successfully for authenticated users."""
    response = await authenticated_client.get("/conversations/new")
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    assert "text/html" in response.headers["content-type"]
    tree = HTMLParser(response.text)
    form = tree.css_first('form[action$="/conversations"][method="post"]')
    assert form is not None, "Form ending with action='/conversations' not found"
    assert (
        form.css_first('input[name="invitee_username"]') is not None
    ), "Input for invitee_username not found"
    assert (
        form.css_first('textarea[name="initial_message"]') is not None
    ), "Textarea for initial_message not found"
    assert (
        form.css_first('button[type="submit"]') is not None
    ), "Submit button not found"


async def test_get_new_conversation_form_unauthenticated(test_client: AsyncClient):
    """Test GET /conversations/new requires authentication."""
    response = await test_client.get("/conversations/new")
    assert (
        response.status_code == 401
    ), f"Expected 401 Unauthorized, got {response.status_code}"
