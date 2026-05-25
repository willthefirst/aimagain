"""Tests for onboarding wizard service functions.

Covers the atomic create path, verification-failure retention, and rollback on
pipeline exception.
"""

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.logic.onboarding.schema import FirstOpeningForm, VerifyForm
from src.domain.logic.onboarding.services import (
    create_first_opening,
    verify_and_create_clinician,
)
from src.domain.logic.verifications import oig as oig_module
from src.domain.models import OpeningDetail, Provider, ProviderLicensure, Verification
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio

_LEIE_FIXTURE = (
    Path(__file__).parents[4]
    / "tests"
    / "logic"
    / "verifications"
    / "test_data"
    / "leie_sample.csv"
)

_VALID_FORM = VerifyForm(
    first_name="Alice",
    last_name="Smith",
    work_email="alice@example.com",
    license_type="lcsw",
    license_number="LIC123",
    issuing_state="CA",
)


@pytest.fixture(autouse=True)
def _patch_external_apis(monkeypatch):
    """Point OIG at the local LEIE fixture and stub NPPES to return a
    matching result so scoring yields 'verified' in the happy path."""
    monkeypatch.setenv("LEIE_CSV_PATH", str(_LEIE_FIXTURE))
    oig_module._reset_cache_for_tests()

    from src.domain.logic.verifications import handlers as handlers_mod

    def _payload(npi: str) -> dict[str, Any]:
        return {"results": [{"basic": {"first_name": "Alice", "last_name": "Smith"}}]}

    def _handler(request: httpx.Request) -> httpx.Response:
        npi = request.url.params.get("number") or ""
        return httpx.Response(200, content=json.dumps(_payload(npi)).encode())

    class _StubAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(handlers_mod.httpx, "AsyncClient", _StubAsyncClient)
    yield
    oig_module._reset_cache_for_tests()


async def _seed_user(db_test_session_manager: async_sessionmaker[AsyncSession]):
    user = create_test_user(username=f"wizard-{uuid.uuid4()}")
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
    return user


async def test_happy_path_creates_provider_licensure_verification(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """verify_and_create_clinician creates Provider + Licensure + Verification rows."""
    user = await _seed_user(db_test_session_manager)

    async with db_test_session_manager() as session:
        provider = await verify_and_create_clinician(_VALID_FORM, user, db=session)

    assert provider.id is not None

    async with db_test_session_manager() as session:
        # Provider row exists
        p = await session.get(Provider, provider.id)
        assert p is not None
        assert p.owner_id == user.id

        # Licensure row exists
        licensures = (
            (
                await session.execute(
                    select(ProviderLicensure).filter(
                        ProviderLicensure.clinician_id == p.clinician_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(licensures) == 1
        assert licensures[0].license_type == "lcsw"
        assert licensures[0].license_number == "LIC123"

        # Verification row exists
        verifications = (
            (
                await session.execute(
                    select(Verification).filter(Verification.provider_id == p.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(verifications) == 1


async def test_failed_verification_does_not_rollback_clinician(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """When verification yields 'failed', the Provider/Licensure rows are kept.
    The wizard surfaces the failure to the user rather than hiding it.
    """
    user = await _seed_user(db_test_session_manager)

    # Override NPPES to return not-found → scoring yields 'failed'
    from src.domain.logic.verifications import handlers as handlers_mod

    def _not_found_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"results": []}')

    class _NotFoundClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(_not_found_handler))

    with patch.object(handlers_mod.httpx, "AsyncClient", _NotFoundClient):
        async with db_test_session_manager() as session:
            provider = await verify_and_create_clinician(_VALID_FORM, user, db=session)

    # Provider still exists
    async with db_test_session_manager() as session:
        p = await session.get(Provider, provider.id)
        assert p is not None

        # Verification exists with failed status
        verif = (
            (
                await session.execute(
                    select(Verification).filter(Verification.provider_id == p.id)
                )
            )
            .scalars()
            .first()
        )
        assert verif is not None
        assert verif.status == "failed"


async def test_create_first_opening_happy_path(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """create_first_opening creates a Post + OpeningDetail with slot fields."""
    user = await _seed_user(db_test_session_manager)

    # Must have a verified clinician first (verify_and_create_clinician commits)
    async with db_test_session_manager() as session:
        provider = await verify_and_create_clinician(_VALID_FORM, user, db=session)

    # Reload user to have providers eager-loaded (selectin) in a new session
    async with db_test_session_manager() as session:
        from src.domain.models import User as UserModel

        fresh_user = await session.get(UserModel, user.id)
        assert fresh_user is not None

        form = FirstOpeningForm(
            opening_type="individual",
            specialties=["Trauma/PTSD", "Anxiety"],
            availability_state="taking_now",
            colleague_note="Taking adult clients now.",
        )
        created_post = await create_first_opening(form, fresh_user, db=session)

    assert created_post.id is not None
    assert created_post.kind == "clinician_opening"
    assert created_post.owner_id == user.id

    # Verify OpeningDetail has the slot fields
    async with db_test_session_manager() as session:
        detail = await session.get(OpeningDetail, created_post.id)
        assert detail is not None
        assert detail.provider_id == provider.id
        assert detail.opening_type == "individual"
        assert detail.availability_state == "taking_now"
        assert detail.colleague_note == "Taking adult clients now."
        assert "Trauma/PTSD" in detail.specialties


async def test_atomicity_on_pipeline_raise(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """If run_provider_verification raises before committing, no Provider or
    Licensure rows persist — the flushed state is rolled back with the session.
    """
    user = await _seed_user(db_test_session_manager)

    from src.domain.logic.onboarding import services as services_mod

    with patch.object(
        services_mod,
        "run_provider_verification",
        new_callable=AsyncMock,
        side_effect=RuntimeError("pipeline exploded"),
    ):
        with pytest.raises(RuntimeError, match="pipeline exploded"):
            async with db_test_session_manager() as session:
                await verify_and_create_clinician(_VALID_FORM, user, db=session)

    # No Provider rows for this user
    async with db_test_session_manager() as session:
        providers = (
            (
                await session.execute(
                    select(Provider).filter(Provider.owner_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert providers == []
