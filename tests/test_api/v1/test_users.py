import pytest
from httpx import AsyncClient

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio

API_PREFIX = "/api/v1"


async def test_list_users_empty(test_client: AsyncClient):
    """Test GET /users returns 200 and an empty list when no users exist."""
    response = await test_client.get(f"{API_PREFIX}/users")

    assert response.status_code == 200
    assert response.json() == [] 