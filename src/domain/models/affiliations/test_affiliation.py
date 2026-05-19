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
    PR 3's reads can navigate to via `provider.primary_affiliation`.
    The transient row is the first / primary affiliation for the
    Provider; #642 PR 1 lets the user add more later via the inline
    list on the edit page."""
    user = _make_user("alice")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    assert len(provider.affiliations) == 1
    aff = provider.primary_affiliation
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
async def test_provider_construct_with_existing_affiliations_skips_auto_create():
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
    provider = _make_provider(owner=user, org=org, affiliations=[existing])
    assert provider.affiliations == [existing]
    assert provider.primary_affiliation is existing


@pytest.mark.asyncio
async def test_provider_per_role_writes_land_on_affiliation():
    """After #635 PR B the per-role columns no longer live on
    `providers` — they live only on `affiliations`. The `Provider`
    ORM class exposes each per-role attr as a `@property` whose setter
    proxies through to `provider.primary_affiliation`, so the
    framework's `repo.patch(provider, location_city='Queens')` (which
    calls `setattr(provider, ...)`) lands the write directly on the
    primary affiliation row. After #642 PR 1 a Provider may hold
    multiple Affiliations — the per-role property proxies target the
    primary one (oldest by `created_at`).
    """
    user = _make_user("dave")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    aff = provider.primary_affiliation
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
    # Reads through the Provider's property proxies return the same
    # value the affiliation now holds — `ProviderRead.model_validate`
    # picks up post-edit values via `from_attributes`.
    assert provider.location_city == "Queens"
    assert provider.in_person_sessions == "no"
    assert provider.sliding_scale is True


@pytest.mark.asyncio
async def test_provider_affiliations_persist_via_cascade(session):
    """`Provider.affiliations` has `cascade="all, delete-orphan"`, so
    persisting a Provider with transient Affiliations flushes every
    row in one shot — no explicit `session.add(...)` per affiliation
    needed."""
    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org)
    session.add_all([user, org, provider])
    await session.flush()
    await session.refresh(provider)
    assert len(provider.affiliations) == 1
    aff = provider.primary_affiliation
    assert aff is not None
    assert aff.id is not None
    assert aff.provider_id == provider.id


@pytest.mark.asyncio
async def test_provider_supports_multiple_affiliations(session):
    """A Provider may hold multiple Affiliations after #642 PR 1 (the
    UNIQUE on ``affiliations.provider_id`` was dropped in
    ``7c3c296c9429``). Each row persists in the same transaction; the
    cascade rule still wipes them all on Provider delete."""
    from src.domain.models import Affiliation

    user = _make_user("erin")
    org_a = _make_org("Acme", user.id)
    org_b = _make_org("Beta", user.id)
    provider = _make_provider(owner=user, org=org_a)
    # Append a second affiliation at a different org with different
    # per-role attributes — the kind of row #642 PR 1's inline list
    # exists to manage.
    provider.affiliations.append(
        Affiliation(
            clinician=provider.clinician,
            org_id=org_b.id,
            location_city="Manhattan",
            location_state="NY",
            location_zip="10001",
            in_person_sessions="no",
            virtual_sessions="yes",
            accepts_out_of_network=False,
            in_network_carriers=[],
            sliding_scale=True,
            cost="$200/session",
        )
    )
    session.add_all([user, org_a, org_b, provider])
    await session.flush()
    await session.refresh(provider)
    assert len(provider.affiliations) == 2
    # Both rows point at the same Provider.
    assert all(a.provider_id == provider.id for a in provider.affiliations)


@pytest.mark.asyncio
async def test_primary_affiliation_picks_oldest_by_created_at(session):
    """`primary_affiliation` returns the oldest Affiliation by
    ``created_at`` — the SQLAlchemy `order_by` on `Provider.affiliations`
    pins the ordering. After #642 PR 1 the directory listing and the
    post-opening dropdown labels both dereference through this property
    so the per-row affiliation is deterministic."""
    import datetime as _dt

    from src.domain.models import Affiliation

    user = _make_user("frank")
    org_a = _make_org("Acme", user.id)
    org_b = _make_org("Beta", user.id)
    provider = _make_provider(owner=user, org=org_a)
    older_aff = provider.affiliations[0]
    # Pin the older affiliation's created_at so the comparison is
    # deterministic regardless of flush clock resolution.
    older_aff.created_at = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)
    newer = Affiliation(
        clinician=provider.clinician,
        org_id=org_b.id,
        location_city="Manhattan",
        location_state="NY",
        location_zip="10001",
        in_person_sessions="no",
        virtual_sessions="yes",
        accepts_out_of_network=False,
        in_network_carriers=[],
        sliding_scale=True,
    )
    newer.created_at = _dt.datetime(2025, 1, 1, tzinfo=_dt.timezone.utc)
    provider.affiliations.append(newer)
    session.add_all([user, org_a, org_b, provider])
    await session.flush()
    await session.refresh(provider)
    assert provider.primary_affiliation is older_aff
