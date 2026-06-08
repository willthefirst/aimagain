"""Model-layer tests for :class:`ClinicianAffiliation` and the 1:1 link to
:class:`Clinician`.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.models import Clinician, ClinicianAffiliation, Organization, User


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
        owner_id=owner_id,
    )


def _make_clinician(*, owner: User, org: Organization, **overrides) -> Clinician:
    defaults = dict(
        owner_id=owner.id,
        org_id=org.id,
        first_name="Jane",
        last_name="Smith",
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
    return Clinician(**defaults)


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


@pytest.mark.asyncio
async def test_clinician_construct_auto_creates_affiliation_with_per_role_attrs():
    """The Clinician constructor pre-populates a transient ClinicianAffiliation
    with the same per-role attributes so the framework's generic create
    handler — which builds the model via
    `spec.model(**payload.model_dump())` — keeps producing rows that
    reads can navigate to via `clinician.primary_clinician_affiliation`.
    The transient row is the first / primary affiliation for the
    Clinician; additional affiliations can be added later via the inline
    list on the edit page."""
    user = _make_user("alice")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    assert len(clinician.clinician_affiliations) == 1
    aff = clinician.primary_clinician_affiliation
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
    # ClinicianAffiliation shares the Clinician directly.
    assert aff.clinician is clinician


@pytest.mark.asyncio
async def test_clinician_construct_with_existing_affiliations_skips_auto_create():
    """Test fixtures wiring the join manually must not be clobbered."""
    user = _make_user("bob")
    org = _make_org("Acme", user.id)
    existing = ClinicianAffiliation(
        clinician_id=uuid.uuid4(),
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="no",
        accepts_out_of_network=False,
        in_network_carriers=[],
        sliding_scale=False,
    )
    clinician = _make_clinician(owner=user, org=org, clinician_affiliations=[existing])
    assert clinician.clinician_affiliations == [existing]
    assert clinician.primary_clinician_affiliation is existing


@pytest.mark.asyncio
async def test_clinician_per_role_writes_land_on_affiliation():
    """The per-role columns live only on `affiliations`. The `Clinician`
    ORM class exposes each per-role attr as a `@property` whose setter
    proxies through to `clinician.primary_clinician_affiliation`, so the
    framework's `repo.patch(clinician, location_city='Queens')` (which
    calls `setattr(clinician, ...)`) lands the write directly on the
    primary affiliation row. A Clinician may hold multiple Affiliations
    — the per-role property proxies target the primary one (oldest by
    `created_at`).
    """
    user = _make_user("dave")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    aff = clinician.primary_clinician_affiliation
    assert aff is not None

    clinician.location_city = "Queens"
    clinician.in_person_sessions = "no"
    clinician.sliding_scale = True
    clinician.cost = "$300/session"
    clinician.in_network_carriers = ["bcbs", "cigna"]

    assert aff.location_city == "Queens"
    assert aff.in_person_sessions == "no"
    assert aff.sliding_scale is True
    assert aff.cost == "$300/session"
    assert aff.in_network_carriers == ["bcbs", "cigna"]
    # Reads through the Clinician's property proxies return the same
    # value the affiliation now holds — `ClinicianRead.model_validate`
    # picks up post-edit values via `from_attributes`.
    assert clinician.location_city == "Queens"
    assert clinician.in_person_sessions == "no"
    assert clinician.sliding_scale is True


@pytest.mark.asyncio
async def test_clinician_affiliations_persist_via_cascade(session):
    """`Clinician.clinician_affiliations` has `cascade="all, delete-orphan"`, so
    persisting a Clinician with transient Affiliations flushes every
    row in one shot — no explicit `session.add(...)` per affiliation
    needed."""
    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    session.add_all([user, org, clinician])
    await session.flush()
    await session.refresh(clinician)
    assert len(clinician.clinician_affiliations) == 1
    aff = clinician.primary_clinician_affiliation
    assert aff is not None
    assert aff.id is not None
    assert aff.clinician_id == clinician.id


@pytest.mark.asyncio
async def test_clinician_supports_multiple_affiliations(session):
    """A Clinician may hold multiple Affiliations. Each row persists in
    the same transaction; the cascade rule still wipes them all on
    Clinician delete."""
    from src.domain.models import ClinicianAffiliation

    user = _make_user("erin")
    org_a = _make_org("Acme", user.id)
    org_b = _make_org("Beta", user.id)
    clinician = _make_clinician(owner=user, org=org_a)
    # Append a second affiliation at a different org with different
    # per-role attributes.
    clinician.clinician_affiliations.append(
        ClinicianAffiliation(
            clinician=clinician,
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
    session.add_all([user, org_a, org_b, clinician])
    await session.flush()
    await session.refresh(clinician)
    assert len(clinician.clinician_affiliations) == 2
    # Both rows point at the same Clinician.
    assert all(a.clinician_id == clinician.id for a in clinician.clinician_affiliations)


@pytest.mark.asyncio
async def test_primary_affiliation_picks_oldest_by_created_at(session):
    """`primary_clinician_affiliation` returns the oldest ClinicianAffiliation by
    ``created_at`` — the SQLAlchemy `order_by` on `Clinician.clinician_affiliations`
    pins the ordering. The directory listing and the post-opening dropdown
    labels both dereference through this property so the per-row
    affiliation is deterministic."""
    import datetime as _dt

    from src.domain.models import ClinicianAffiliation

    user = _make_user("frank")
    org_a = _make_org("Acme", user.id)
    org_b = _make_org("Beta", user.id)
    clinician = _make_clinician(owner=user, org=org_a)
    older_aff = clinician.clinician_affiliations[0]
    # Pin the older affiliation's created_at so the comparison is
    # deterministic regardless of flush clock resolution.
    older_aff.created_at = _dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc)
    newer = ClinicianAffiliation(
        clinician=clinician,
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
    clinician.clinician_affiliations.append(newer)
    session.add_all([user, org_a, org_b, clinician])
    await session.flush()
    await session.refresh(clinician)
    assert clinician.primary_clinician_affiliation is older_aff
