"""Model round-trip tests for OpeningDetail T3 slot fields.

Verifies that new columns default correctly and can be written/read back.
Uses `BaseRepository.create_polymorphic` (the same path the route handler
uses) to create Post + detail in one flush.
"""

import uuid
from datetime import datetime, timezone

import pytest

from src.domain.models import POST_KIND_BY_DETAIL_MODEL, OpeningDetail, Post
from src.framework.persistence.base_repository import BaseRepository
from tests.helpers import (
    create_test_user,
    make_opening_detail,
    make_provider_with_org,
)

pytestmark = pytest.mark.asyncio


async def _seed_owner_and_provider(db_test_session_manager):
    owner = create_test_user(username=f"owner-{uuid.uuid4()}")
    provider = make_provider_with_org(owner_id=owner.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(owner)
            session.add(provider)
    return owner, provider


async def _create_opening(db_test_session_manager, owner, provider, **overrides):
    post = Post(kind="clinician_opening", owner_id=owner.id)
    detail = make_opening_detail(provider_id=provider.id, **overrides)
    async with db_test_session_manager() as session:
        repo = BaseRepository(session)
        kind_spec = POST_KIND_BY_DETAIL_MODEL[OpeningDetail]
        created = await repo.create_polymorphic(
            post, detail, detail_relationship=kind_spec.detail_relationship
        )
        await session.commit()
        return created.id


async def test_slot_fields_default_to_null_and_empty(db_test_session_manager):
    """JSON arrays default to [] and nullable scalar fields default to None."""
    owner, provider = await _seed_owner_and_provider(db_test_session_manager)
    post_id = await _create_opening(db_test_session_manager, owner, provider)

    async with db_test_session_manager() as session:
        detail = await session.get(OpeningDetail, post_id)
        assert detail.opening_type is None
        assert detail.specialties == []
        assert detail.population_tags == []
        assert detail.fee_low is None
        assert detail.fee_high is None
        assert detail.payment_types == []
        assert detail.availability_state is None
        assert detail.colleague_note is None
        assert detail.note_expires_at is None
        assert detail.last_confirmed_at is not None


async def test_slot_fields_roundtrip(db_test_session_manager):
    """Written slot values survive a flush + re-read."""
    owner, provider = await _seed_owner_and_provider(db_test_session_manager)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    post_id = await _create_opening(
        db_test_session_manager,
        owner,
        provider,
        opening_type="individual",
        specialties=["trauma", "anxiety"],
        population_tags=["lgbtq"],
        fee_low=100,
        fee_high=200,
        payment_types=["sliding_scale"],
        availability_state="taking_now",
        colleague_note="Taking adult clients now.",
        last_confirmed_at=now,
    )

    async with db_test_session_manager() as session:
        detail = await session.get(OpeningDetail, post_id)
        assert detail.opening_type == "individual"
        assert detail.specialties == ["trauma", "anxiety"]
        assert detail.population_tags == ["lgbtq"]
        assert detail.fee_low == 100
        assert detail.fee_high == 200
        assert detail.payment_types == ["sliding_scale"]
        assert detail.availability_state == "taking_now"
        assert detail.colleague_note == "Taking adult clients now."
