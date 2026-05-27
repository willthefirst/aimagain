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
        type="solo_practice",
        parent_org_id=None,
        root_org_id=org_id,
        owner_id=owner_id,
    )


def _make_clinician(
    *, owner: User, org: Organization, npi: str | None = None
) -> Clinician:
    """Builds a fully populated Clinician transient instance."""
    return Clinician(
        owner_id=owner.id,
        org_id=org.id,
        npi=npi,
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
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
    from src.domain.models import Affiliation

    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    existing = Affiliation(
        clinician_id=uuid.uuid4(),
        org_id=org.id,
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
    )
    clinician = Clinician(
        owner_id=user.id,
        npi="9876543210",
        affiliations=[existing],
    )
    assert clinician.affiliations == [existing]
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
    clinician = Clinician(npi="12345")  # 5 digits, not 10
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
        in_person_sessions="yes",
        virtual_sessions="no",
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
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
