"""Route-level tests for `POST /clinicians/{provider_id}/verifications`.

Covers the wire shape: superuser-only authorization, 404 on missing
provider, 201 + `Location` header on the happy path, and a persisted
`Verification` row after the call. Uses a `respx`-free `httpx.MockTransport`
patched into the orchestrator's `httpx.AsyncClient` via a thin
monkeypatched factory so the integration test never reaches the public
NPPES endpoint.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.verifications import oig as oig_module
from src.domain.models import User, Verification
from tests.helpers import create_test_user, make_provider_with_org, promote_to_admin

pytestmark = pytest.mark.asyncio

_LEIE_FIXTURE = (
    Path(__file__).parent.parent
    / "logic"
    / "verifications"
    / "test_data"
    / "leie_sample.csv"
)


@pytest.fixture(autouse=True)
def _patch_external_apis(monkeypatch):
    """Point OIG at the local LEIE fixture, and replace
    `httpx.AsyncClient` *inside the handlers module* with a mock-
    transport variant. The handler calls
    `async with httpx.AsyncClient(timeout=...) as http:`; monkeypatching
    the symbol there lets the route test exercise the full stack without
    hitting NPPES."""
    monkeypatch.setenv("LEIE_CSV_PATH", str(_LEIE_FIXTURE))
    oig_module._reset_cache_for_tests()

    from src.domain.logic.verifications import handlers as handlers_mod

    def _payload(npi: str) -> dict[str, Any]:
        return {
            "results": [
                {"basic": {"first_name": "MockedFirst", "last_name": "MockedLast"}}
            ]
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        npi = request.url.params.get("number") or ""
        return httpx.Response(200, content=json.dumps(_payload(npi)).encode())

    class _StubAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(handlers_mod.httpx, "AsyncClient", _StubAsyncClient)
    yield
    oig_module._reset_cache_for_tests()


async def _seed_provider(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    *,
    npi: str | None = "1234567890",
) -> uuid.UUID:
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            provider = make_provider_with_org(owner_id=owner.id, npi=npi)
            session.add(provider)
        return provider.id


async def test_non_superuser_gets_403(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """`current_admin_user` rejects non-superusers — fastapi-users
    returns 403 (not 401, since the user *is* authenticated)."""
    provider_id = await _seed_provider(db_test_session_manager)
    response = await authenticated_client.post(
        f"/clinicians/{provider_id}/verifications"
    )
    assert response.status_code == 403


async def test_admin_happy_path_returns_201_and_persists(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    """Promoted admin → orchestrator runs end-to-end → 201 with the new
    row's id + a `Location` header pointing at the per-verification URL."""
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    provider_id = await _seed_provider(db_test_session_manager, npi="1234567890")

    response = await authenticated_client.post(
        f"/clinicians/{provider_id}/verifications"
    )
    assert response.status_code == 201
    body = response.json()
    verification_id = uuid.UUID(body["id"])
    assert body["status"] in {"verified", "needs_review", "failed"}
    assert (
        response.headers["Location"]
        == f"/clinicians/{provider_id}/verifications/{verification_id}"
    )

    async with db_test_session_manager() as session:
        row = (
            (
                await session.execute(
                    select(Verification).filter(Verification.id == verification_id)
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.provider_id == provider_id


async def test_admin_404_for_missing_provider(
    authenticated_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
    logged_in_user: User,
):
    await promote_to_admin(db_test_session_manager, logged_in_user.email)
    bogus = uuid.uuid4()
    response = await authenticated_client.post(f"/clinicians/{bogus}/verifications")
    assert response.status_code == 404


async def test_anon_gets_401_or_redirect(
    test_client: AsyncClient,
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """An unauthenticated request must not be able to invoke the
    pipeline. fastapi-users returns 401 for cookie-auth misses; the
    contract for this route is "anyone unauthorized doesn't get in"
    rather than a specific code, so accept 401 or 403."""
    provider_id = await _seed_provider(db_test_session_manager)
    response = await test_client.post(f"/clinicians/{provider_id}/verifications")
    assert response.status_code in {401, 403}
