"""Tests for the four `ProviderProfile`-family models.

Exercises the invariants the DB layer owns: the per-user UniqueConstraint
on `provider_profiles`, the cascade from a profile down to its credential
lists, and the CHECK constraints rendered from the controlled-vocabulary
tuples in `post_enums.py`.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import (
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
    ProviderProfile,
)
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _make_profile(user, **overrides) -> ProviderProfile:
    defaults = dict(
        user=user,
        practice_name="Acme Health",
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    return ProviderProfile(**{**defaults, **overrides})


async def test_create_provider_profile_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_profile(user))

    async with db_test_session_manager() as session:
        profile = (
            (
                await session.execute(
                    select(ProviderProfile).filter(ProviderProfile.user_id == user.id)
                )
            )
            .scalars()
            .first()
        )
        assert profile is not None
        assert profile.practice_name == "Acme Health"


async def test_provider_profile_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple provider profiles — the previously-enforced
    `uq_provider_profiles_user_id` constraint was dropped in `8f20a93effc9`."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_profile(user))

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(
                ProviderProfile(
                    user_id=user.id,
                    practice_name="Other Practice",
                    location_city="Springfield",
                    location_state="IL",
                    location_zip="62701",
                    in_person_sessions="yes",
                    virtual_sessions="no",
                )
            )

        result = await session.execute(
            select(ProviderProfile).filter(ProviderProfile.user_id == user.id)
        )
        profiles = result.scalars().all()
        assert len(profiles) == 2
        assert {p.practice_name for p in profiles} == {"Acme Health", "Other Practice"}


async def test_delete_profile_cascades_credentials(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Deleting a `ProviderProfile` removes its licensures, educations,
    and certifications via the FK CASCADE."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            profile = _make_profile(user)
            profile.licensures.append(
                ProviderLicensure(
                    license_type="lcsw",
                    license_number="LCSW-123",
                    issuing_state="IL",
                )
            )
            profile.educations.append(
                ProviderEducation(
                    education_type="msw",
                    institution="State University",
                )
            )
            profile.certifications.append(
                ProviderCertification(
                    certification_type="emdr",
                    certifying_body="EMDRIA",
                )
            )
            session.add(profile)
        profile_id = profile.id

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(ProviderProfile, profile_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        for cls in (ProviderLicensure, ProviderEducation, ProviderCertification):
            rows = (
                (
                    await session.execute(
                        select(cls).filter(cls.profile_id == profile_id)
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
            profile = _make_profile(user)
            session.add(profile)
        profile_id = profile.id

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    ProviderLicensure(
                        profile_id=profile_id,
                        license_type="not_a_real_license",
                        license_number="X-1",
                        issuing_state="IL",
                    )
                )
