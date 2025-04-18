from pydantic import BaseModel
import pytest
from httpx import AsyncClient
import uuid

from app.models import User, Conversation, Participant
from sqlalchemy.ext.asyncio import AsyncSession

from selectolax.parser import HTMLParser
from tests.test_helpers import create_test_user

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class UserCreateRequest(BaseModel):
    email: str
    password: str


async def test_register(test_client: AsyncClient):
    request_data = UserCreateRequest(email="test@test.com", password="test")
    response = await test_client.post(f"/auth/register", json=request_data.model_dump())
    print(response.json())
    assert response.status_code == 201
    assert "application/json" in response.headers["content-type"]
