import pytest
from httpx import AsyncClient

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_users_empty(test_client: AsyncClient):
    """Test GET /users returns HTML with no users message when empty."""
    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Check for specific content indicating emptiness and a link
    assert "No users found" in response.text
    assert f'<a href="{API_PREFIX}/users">' in response.text # Check for refresh link
    assert "<html>" in response.text # Basic structure check 