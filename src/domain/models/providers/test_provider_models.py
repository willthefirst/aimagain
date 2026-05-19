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
    """Build an unbound Provider wired to a fresh root Organization.
    The practice's display name lives on ``provider.org.name`` (#524);
    ``practice_name=...`` kwarg here names the *Organization*. Save-
    update cascade picks the Org up via ``provider.org`` so callers
    keep their single ``session.add(provider)`` shape."""
    practice_name = overrides.pop("practice_name", "Acme Health")
    org = make_organization_row(owner_id=user.id, name=practice_name)
    defaults = dict(
        user=user,
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
        assert provider.org.name == "Acme Health"


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
        assert {p.org.name for p in providers} == {"Acme Health", "Other Practice"}


async def test_delete_provider_leaves_clinician_credentials_intact(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """After #635 PR A, credential sub-tables FK to `clinicians.id`,
    not `providers.id`. Deleting a Provider no longer cascades to
    the credentials — they're person-level data and stay attached to
    the Clinician (which survives the Provider delete in the target
    multi-affiliation model). The Provider cascade is preserved for
    Affiliation; tested in `src/domain/models/affiliations/`."""
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
        clinician_id = provider.clinician_id

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Provider, provider_id)
            await session.delete(loaded)

    async with db_test_session_manager() as session:
        for cls in (ProviderLicensure, ProviderEducation, ProviderCertification):
            rows = (
                (
                    await session.execute(
                        select(cls).filter(cls.clinician_id == clinician_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1, (
                f"{cls.__name__} rows attached to clinician should survive "
                "Provider delete (#635 PR A)"
            )


async def test_provider_accepts_null_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`npi` is nullable — existing rows ship without one."""
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
        assert provider.npi is None


async def test_provider_accepts_10_digit_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_provider(user, npi="1234567890"))

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
        assert provider.npi == "1234567890"


@pytest.mark.parametrize("bad_npi", ["123", "12345678901", "12345abcde", "          "])
async def test_provider_npi_check_constraint_rejects_malformed(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    bad_npi: str,
):
    """`ck_clinicians_npi_format` rejects anything that isn't NULL or
    exactly 10 ASCII digits — defense-in-depth against a wire payload
    that skipped the Pydantic validator. After #629 PR 1 the column
    lives on `clinicians.npi`; `Provider(npi=...)` auto-creates the
    linked `Clinician` and the CHECK fires on flush there."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_provider(user, npi=bad_npi))


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
        clinician_id = provider.clinician_id

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(
                    ProviderLicensure(
                        clinician_id=clinician_id,
                        license_type="not_a_real_license",
                        license_number="X-1",
                        issuing_state="IL",
                    )
                )
