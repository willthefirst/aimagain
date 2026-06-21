"""Model-layer tests for :class:`Clinician`.

Higher-level coverage (routes, audit, view) lives in
``src/domain/routes/test_clinicians.py`` and
``src/domain/logic/clinicians/test_view.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.models import Clinician, Organization, User


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


def _make_clinician(
    *, owner: User, org: Organization, npi: str | None = None
) -> Clinician:
    """Builds a fully populated Clinician transient instance."""
    return Clinician(
        owner_id=owner.id,
        org_id=org.id,
        first_name="Jane",
        last_name="Smith",
        npi=npi,
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
    )


@pytest_asyncio.fixture
async def session(db_test_session_manager: async_sessionmaker):
    async with db_test_session_manager() as s:
        yield s


@pytest.mark.asyncio
async def test_clinician_construct_auto_creates_clinician_with_npi():
    """Passing ``npi=`` to ``Clinician(...)`` should store it on the
    clinician directly — the framework's generic create handler relies
    on this so it can keep calling ``spec.model(**payload.model_dump())``."""
    user = _make_user("alice")
    org = _make_org("Acme Counseling", user.id)
    clinician = _make_clinician(owner=user, org=org, npi="1234567890")
    assert clinician.npi == "1234567890"


@pytest.mark.asyncio
async def test_clinician_construct_without_npi_stores_none():
    user = _make_user("bob")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org, npi=None)
    assert clinician.npi is None


@pytest.mark.asyncio
async def test_clinician_construct_with_existing_affiliation_skips_auto_create():
    """When the caller hands in existing affiliations, the constructor
    must NOT clobber them with a fresh one."""
    from src.domain.models import ClinicianAffiliation

    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    existing = ClinicianAffiliation(
        clinician_id=uuid.uuid4(),
        org_id=org.id,
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
    )
    clinician = Clinician(
        owner_id=user.id,
        first_name="Jane",
        last_name="Smith",
        npi="9876543210",
        clinician_affiliations=[existing],
    )
    assert clinician.clinician_affiliations == [existing]
    assert clinician.npi == "9876543210"


@pytest.mark.asyncio
async def test_setting_clinician_npi_persists(session):
    """``setattr(clinician, 'npi', value)`` — which is what the
    framework's ``handle_update`` does via ``repo.patch`` — must
    persist after flush."""
    user = _make_user("dan")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org, npi="1234567890")
    session.add_all([user, org, clinician])
    await session.flush()

    clinician.npi = "0987654321"
    await session.flush()
    await session.refresh(clinician)
    assert clinician.npi == "0987654321"


@pytest.mark.asyncio
async def test_clinician_npi_check_constraint_rejects_non_ten_digits(session):
    """The CHECK constraint on ``clinicians.npi`` — defense-in-
    depth behind the Pydantic ``_validate_npi``."""
    clinician = Clinician(
        first_name="Jane", last_name="Smith", npi="12345"
    )  # 5 digits, not 10
    session.add(clinician)
    with pytest.raises(IntegrityError):
        await session.flush()


# --- first_name / last_name -------------------------------------------


@pytest.mark.asyncio
async def test_clinician_construct_stores_names():
    """`Clinician(first_name=..., last_name=...)` stores them directly.
    The verification pipeline's `_clinician_names` reads through these."""
    user = _make_user("eve")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    clinician.first_name = "Eva"
    clinician.last_name = "Stone"
    assert clinician.first_name == "Eva"
    assert clinician.last_name == "Stone"


@pytest.mark.asyncio
async def test_clinician_construct_passes_names_as_kwargs():
    """When `first_name` / `last_name` arrive as construct kwargs (the
    framework's `spec.model(**payload.model_dump())` path), they are
    stored on the Clinician directly."""
    user = _make_user("frank")
    org = _make_org("Acme", user.id)
    clinician = Clinician(
        owner_id=user.id,
        org_id=org.id,
        first_name="Frank",
        last_name="Tucker",
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
    )
    assert clinician.first_name == "Frank"
    assert clinician.last_name == "Tucker"


@pytest.mark.asyncio
async def test_setting_clinician_names_persists(session):
    """`setattr(clinician, 'first_name', value)` — the path
    `repo.patch(clinician, first_name="X")` takes — must persist."""
    user = _make_user("gina")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    session.add_all([user, org, clinician])
    await session.flush()

    clinician.first_name = "Gina"
    clinician.last_name = "Hart"
    await session.flush()
    await session.refresh(clinician)
    assert clinician.first_name == "Gina"
    assert clinician.last_name == "Hart"


# --- Per-affiliation proxy setters ---------------------------------------


@pytest.mark.asyncio
async def test_setting_per_affiliation_field_with_no_affiliation_raises():
    """Per-affiliation fields (location, availability, insurance posture,
    cost, org_id) live on :class:`ClinicianAffiliation`. Writing through
    the proxy when no affiliation exists used to silently drop the write
    — the canonical "edit form returned 200 but nothing saved" prod bug
    once create-time affiliation became optional. The setter must now
    refuse the write loudly so the failure is visible."""
    user = _make_user("solo")
    clinician = Clinician(
        owner_id=user.id,
        first_name="Solo",
        last_name="Practitioner",
        npi="1234567890",
    )
    assert clinician.primary_clinician_affiliation is None
    for attr, value in (
        ("org_id", uuid.uuid4()),
        ("location_city", "Brooklyn"),
        ("location_state", "NY"),
        ("accepts_out_of_network", True),
        ("in_network_carriers", []),
        ("sliding_scale", False),
    ):
        with pytest.raises(ValueError, match=f"cannot set '{attr}'"):
            setattr(clinician, attr, value)


@pytest.mark.asyncio
async def test_setting_per_affiliation_field_with_affiliation_writes_through():
    """When a primary affiliation exists the proxy setter writes through
    to it — the path the clinician edit form takes for any clinician
    that has one."""
    user = _make_user("affd")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    assert clinician.primary_clinician_affiliation is not None

    clinician.location_city = "Queens"
    assert clinician.primary_clinician_affiliation.location_city == "Queens"


# --- Claim A verification columns -----------------------------------------


@pytest.mark.asyncio
async def test_clinician_verification_defaults(session):
    """A freshly created Clinician without explicit verification kwargs
    should land in the "no claim yet" state: `npi_match_status='none'`,
    `clinician_verified=False`, and the timestamp columns NULL."""
    user = _make_user("hank")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    session.add_all([user, org, clinician])
    await session.flush()
    await session.refresh(clinician)
    assert clinician.npi_match_status == "none"
    assert clinician.clinician_verified is False
    assert clinician.npi_verified_at is None
    assert clinician.verified_at is None
    assert clinician.ever_verified_at is None


@pytest.mark.asyncio
async def test_clinician_npi_match_status_check_constraint_rejects_unknown(session):
    """The `ck_clinicians_npi_match_status` CHECK keeps the column on
    the closed `NpiMatchStatus` vocab — defense in depth behind the
    Python enum."""
    user = _make_user("ivy")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org)
    session.add_all([user, org, clinician])
    await session.flush()

    clinician.npi_match_status = "not_a_real_value"
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.asyncio
async def test_clinician_verification_columns_persist(session):
    """Round-trip: setting the verification cache columns persists
    through flush + refresh. The Phase 3 `recompute_clinician_claim`
    helper writes through these same attrs."""
    import datetime as _dt

    user = _make_user("jane")
    org = _make_org("Acme", user.id)
    clinician = _make_clinician(owner=user, org=org, npi="1234567890")
    session.add_all([user, org, clinician])
    await session.flush()

    now = _dt.datetime(2026, 1, 1, 12, 0, 0)
    clinician.npi_match_status = "matched"
    clinician.npi_verified_at = now
    clinician.clinician_verified = True
    clinician.verified_at = now
    clinician.ever_verified_at = now
    await session.flush()
    await session.refresh(clinician)
    assert clinician.npi_match_status == "matched"
    assert clinician.npi_verified_at == now
    assert clinician.clinician_verified is True
    assert clinician.verified_at == now
    assert clinician.ever_verified_at == now
