"""Model-layer tests for :class:`Affiliation` and the 1:1 link to
:class:`Provider` introduced in #629 PR 2.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.models import Affiliation, Organization, Provider, User


def _make_user(username: str) -> User:
    return User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )


def _make_org(name: str, owner_id) -> Organization:
    org_id = uuid.uuid4()
    return Organization(
        id=org_id,
        name=name,
        type="solo_practice",
        parent_org_id=None,
        root_org_id=org_id,
        owner_id=owner_id,
    )


def _make_provider(*, owner: User, org: Organization, **overrides) -> Provider:
    defaults = dict(
        owner_id=owner.id,
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        accepts_out_of_network=True,
        in_network_carriers=["aetna"],
        sliding_scale=False,
        cost="$150/session",
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
    )
    defaults.update(overrides)
    return Provider(**defaults)


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


@pytest.mark.asyncio
async def test_provider_construct_auto_creates_affiliation_with_per_role_attrs():
    """The Provider constructor pre-populates a transient Affiliation
    with the same per-role attributes so the framework's generic create
    handler — which builds the model via
    `spec.model(**payload.model_dump())` — keeps producing rows that
    PR 3's reads can navigate to via `provider.affiliation`."""
    user = _make_user("alice")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    aff = provider.affiliation
    assert aff is not None
    assert aff.org_id == org.id
    assert aff.in_person_sessions == "yes"
    assert aff.virtual_sessions == "please_contact"
    assert aff.accepts_out_of_network is True
    assert aff.in_network_carriers == ["aetna"]
    assert aff.sliding_scale is False
    assert aff.cost == "$150/session"
    assert aff.location_city == "Brooklyn"
    assert aff.location_state == "NY"
    assert aff.location_zip == "11201"
    # Affiliation shares the Clinician with its Provider so the
    # `clinician × org` relationship is well-defined.
    assert aff.clinician is provider.clinician


@pytest.mark.asyncio
async def test_provider_construct_with_existing_affiliation_skips_auto_create():
    """Test fixtures wiring the join manually must not be clobbered."""
    user = _make_user("bob")
    org = _make_org("Acme", user.id)
    existing = Affiliation(
        clinician_id=uuid.uuid4(),
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="no",
        accepts_out_of_network=False,
        in_network_carriers=[],
        sliding_scale=False,
    )
    provider = _make_provider(owner=user, org=org, affiliation=existing)
    assert provider.affiliation is existing


@pytest.mark.asyncio
async def test_provider_per_role_writes_mirror_to_affiliation():
    """Regression for #629 PR 4 — `setattr(provider, '<per-role>', value)`
    must mirror the write onto `provider.affiliation` so PR 3's
    affiliation-first reads see the post-edit value. Without the
    mirror, `repo.patch(provider, location_city='Queens')` would
    update `providers.location_city` but leave
    `affiliations.location_city` stale, and the directory's
    `provider_card_view._role_attr` would return the pre-edit
    affiliation value."""
    user = _make_user("dave")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    aff = provider.affiliation
    assert aff is not None

    provider.location_city = "Queens"
    provider.in_person_sessions = "no"
    provider.sliding_scale = True
    provider.cost = "$300/session"
    provider.in_network_carriers = ["bcbs", "cigna"]

    assert aff.location_city == "Queens"
    assert aff.in_person_sessions == "no"
    assert aff.sliding_scale is True
    assert aff.cost == "$300/session"
    assert aff.in_network_carriers == ["bcbs", "cigna"]


@pytest.mark.asyncio
async def test_provider_affiliation_persists_via_cascade(session):
    """`Provider.affiliation` has `cascade="all, delete-orphan"`, so
    persisting a Provider with a transient Affiliation flushes both
    rows in one shot — no explicit `session.add(provider.affiliation)`
    needed."""
    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    session.add_all([user, org, provider])
    await session.flush()
    await session.refresh(provider)
    assert provider.affiliation is not None
    assert provider.affiliation.id is not None
    assert provider.affiliation.provider_id == provider.id
