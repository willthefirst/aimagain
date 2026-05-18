"""Tests for the four `Provider`-family models.

Exercises the invariants the DB layer owns: that multiple `Provider` rows
per user are allowed (the original `uq_provider_profiles_user_id` was
dropped in `8f20a93effc9`), the cascade from a `Provider` down to its
credential lists, and the CHECK constraints rendered from the
controlled-vocabulary tuples in `enums.py`.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    Provider,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
)
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


def _make_provider(user, **overrides) -> Provider:
    """Build an unbound Provider wired to a fresh root Organization so
    the PR 2 NOT-NULL ``org_id`` + mirror invariant hold at flush time.
    Save-update cascade picks the Org up via ``provider.org``; callers
    can keep their pre-PR-2 ``session.add(provider)`` shape."""
    practice_name = overrides.pop("practice_name", "Acme Health")
    org = make_organization_row(owner_id=user.id, name=practice_name)
    defaults = dict(
        user=user,
        practice_name=practice_name,
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    provider = Provider(org_id=org.id, **{**defaults, **overrides})
    provider.org = org
    return provider


async def test_create_provider_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_provider(user))

    async with db_test_session_manager() as session:
        provider = (
            (
                await session.execute(
                    select(Provider).filter(Provider.owner_id == user.id)
                )
            )
            .scalars()
            .first()
        )
        assert provider is not None
        assert provider.practice_name == "Acme Health"


async def test_provider_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple providers — the previously-enforced
    `uq_provider_profiles_user_id` constraint was dropped in `8f20a93effc9`."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_provider(user))

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_make_provider(user, practice_name="Other Practice"))

        result = await session.execute(
            select(Provider).filter(Provider.owner_id == user.id)
        )
        providers = result.scalars().all()
        assert len(providers) == 2
        assert {p.practice_name for p in providers} == {"Acme Health", "Other Practice"}


async def test_delete_provider_cascades_credentials(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a `Provider` removes its licensures, educations,
    and certifications via the FK CASCADE."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            provider = _make_provider(user)
            provider.licensures.append(
                ProviderLicensure(
                    license_type="lcsw",
                    license_number="LCSW-123",
                    issuing_state="IL",
                )
            )
            provider.educations.append(
                ProviderEducation(
                    education_type="msw",
                    institution="State University",
                )
            )
            provider.certifications.append(
                ProviderCertification(
                    certification_type="emdr",
                    certifying_body="EMDRIA",
                )
            )
            session.add(provider)
        provider_id = provider.id

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Provider, provider_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        for cls in (ProviderLicensure, ProviderEducation, ProviderCertification):
            rows = (
                (
                    await session.execute(
                        select(cls).filter(cls.provider_id == provider_id)
                    )
                )
                .scalars()
                .all()
            )
            assert rows == [], f"{cls.__name__} rows survived parent delete"


async def test_invalid_license_type_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`license_type` must be one of `LICENSE_TYPES` — bogus values rejected."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            provider = _make_provider(user)
            session.add(provider)
        provider_id = provider.id

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    ProviderLicensure(
                        provider_id=provider_id,
                        license_type="not_a_real_license",
                        license_number="X-1",
                        issuing_state="IL",
                    )
                )
