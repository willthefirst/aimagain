"""Model-layer tests for :class:`Clinician` and its 1:1 link to
:class:`Provider` (the structural setup #629 PR 1 introduces).

Higher-level coverage (routes, audit, view) lives in
``src/domain/routes/test_providers.py`` and
``src/domain/logic/providers/test_view.py`` — those exercise the
flow through `provider.npi` (which is the property that now reads
``provider.clinician.npi``).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.domain.models import Clinician, Organization, Provider, User


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


def _make_provider(
    *, owner: User, org: Organization, npi: str | None = None
) -> Provider:
    """Builds a fully populated Provider transient instance. The
    `npi=...` kwarg flows through :meth:`Provider.__init__` and
    auto-creates the linked Clinician (#629 PR 1)."""
    return Provider(
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
async def test_provider_construct_auto_creates_clinician_with_npi():
    """Passing ``npi=`` to ``Provider(...)`` should produce a
    transient ``Clinician`` attached to ``provider.clinician`` —
    the framework's generic create handler relies on this so it
    can keep calling ``spec.model(**payload.model_dump())`` after
    the column move."""
    user = _make_user("alice")
    org = _make_org("Acme Counseling", user.id)
    provider = _make_provider(owner=user, org=org, npi="1234567890")
    assert provider.clinician is not None
    assert provider.clinician.npi == "1234567890"
    # `provider.npi` proxies through the clinician.
    assert provider.npi == "1234567890"


@pytest.mark.asyncio
async def test_provider_construct_without_npi_creates_clinician_with_none():
    user = _make_user("bob")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org, npi=None)
    assert provider.clinician is not None
    assert provider.clinician.npi is None
    assert provider.npi is None


@pytest.mark.asyncio
async def test_provider_construct_with_existing_clinician_skips_auto_create():
    """When the caller hands in an existing Clinician (the PR 2 case
    where multiple providers share one clinician), the constructor
    must NOT clobber it with a fresh one."""
    user = _make_user("carol")
    org = _make_org("Acme", user.id)
    existing = Clinician(npi="9876543210")
    provider = Provider(
        owner_id=user.id,
        org_id=org.id,
        clinician=existing,
        in_person_sessions="yes",
        virtual_sessions="please_contact",
        accepts_out_of_network=True,
        in_network_carriers=[],
        sliding_scale=False,
        location_city="Brooklyn",
        location_state="NY",
        location_zip="11201",
    )
    assert provider.clinician is existing
    assert provider.npi == "9876543210"


@pytest.mark.asyncio
async def test_setting_provider_npi_writes_to_linked_clinician(session):
    """``setattr(provider, 'npi', value)`` — which is what the
    framework's ``handle_update`` does via ``repo.patch`` — must
    route to ``provider.clinician.npi`` so updates persist after
    the column move."""
    user = _make_user("dan")
    org = _make_org("Acme", user.id)
    provider = _make_provider(owner=user, org=org, npi="1234567890")
    session.add_all([user, org, provider])
    await session.flush()

    provider.npi = "0987654321"
    await session.flush()
    await session.refresh(provider)
    assert provider.clinician.npi == "0987654321"
    assert provider.npi == "0987654321"


@pytest.mark.asyncio
async def test_clinician_npi_check_constraint_rejects_non_ten_digits(session):
    """The CHECK constraint that previously lived on
    ``providers.npi`` now lives on ``clinicians.npi`` — defense-in-
    depth behind the Pydantic ``_validate_npi``."""
    clinician = Clinician(npi="12345")  # 5 digits, not 10
    session.add(clinician)
    with pytest.raises(IntegrityError):
        await session.flush()
