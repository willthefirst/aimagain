"""Tests for the four `ProviderLicensure`/`ProviderEducation`/`ProviderCertification`
credential models and the `Clinician` root they attach to.

Exercises the invariants the DB layer owns: that multiple `Clinician` rows
per user are allowed, the cascade from a `Clinician` down to its
credential lists, and the CHECK constraints rendered from the
controlled-vocabulary tuples in `enums.py`.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import (
    Clinician,
    ProviderCertification,
    ProviderEducation,
    ProviderLicensure,
)
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


def _make_clinician(user, **overrides) -> Clinician:
    """Build an unbound Clinician wired to a fresh root Organization.
    The practice's display name lives on the primary affiliation's org;
    ``practice_name=...`` kwarg here names the *Organization*. Save-
    update cascade picks the Org up via the affiliation so callers
    keep their single ``session.add(clinician)`` shape."""
    practice_name = overrides.pop("practice_name", "Acme Health")
    org = make_organization_row(owner_id=user.id, name=practice_name)
    defaults = dict(
        owner_id=user.id,
        org_id=org.id,
        location_city="Springfield",
        location_state="IL",
        location_zip="62701",
        in_person_sessions="yes",
        virtual_sessions="no",
    )
    clinician = Clinician(**{**defaults, **overrides})
    clinician.org = org
    return clinician


async def test_create_clinician_persists(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_clinician(user))

    async with db_test_session_manager() as session:
        clinician = (
            (
                await session.execute(
                    select(Clinician).filter(Clinician.owner_id == user.id)
                )
            )
            .scalars()
            .first()
        )
        assert clinician is not None
        assert clinician.org.name == "Acme Health"


async def test_clinician_allows_multiple_per_user(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A user may own multiple clinicians."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_clinician(user))

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(_make_clinician(user, practice_name="Other Practice"))

        result = await session.execute(
            select(Clinician).filter(Clinician.owner_id == user.id)
        )
        clinicians = result.scalars().all()
        assert len(clinicians) == 2
        assert {c.org.name for c in clinicians} == {"Acme Health", "Other Practice"}


async def test_delete_clinician_cascades_to_credentials(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Credential sub-tables FK to `clinicians.id` with ON DELETE CASCADE.
    Deleting a Clinician wipes its credentials."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            clinician = _make_clinician(user)
            clinician.licensures.append(
                ProviderLicensure(
                    license_type="lcsw",
                    license_number="LCSW-123",
                    issuing_state="IL",
                )
            )
            clinician.educations.append(
                ProviderEducation(
                    education_type="msw",
                    institution="State University",
                )
            )
            clinician.certifications.append(
                ProviderCertification(
                    certification_type="emdr",
                    certifying_body="EMDRIA",
                )
            )
            session.add(clinician)
        clinician_id = clinician.id

    async with db_test_session_manager() as session:
        async with session.begin():
            loaded = await session.get(Clinician, clinician_id)
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
            assert (
                len(rows) == 0
            ), f"{cls.__name__} rows should be removed by Clinician cascade"


async def test_clinician_accepts_null_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`npi` is nullable — existing rows ship without one."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_clinician(user))

    async with db_test_session_manager() as session:
        clinician = (
            (
                await session.execute(
                    select(Clinician).filter(Clinician.owner_id == user.id)
                )
            )
            .scalars()
            .first()
        )
        assert clinician is not None
        assert clinician.npi is None


async def test_clinician_accepts_10_digit_npi(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            session.add(_make_clinician(user, npi="1234567890"))

    async with db_test_session_manager() as session:
        clinician = (
            (
                await session.execute(
                    select(Clinician).filter(Clinician.owner_id == user.id)
                )
            )
            .scalars()
            .first()
        )
        assert clinician is not None
        assert clinician.npi == "1234567890"


@pytest.mark.parametrize("bad_npi", ["123", "12345678901", "12345abcde", "          "])
async def test_clinician_npi_check_constraint_rejects_malformed(
    db_test_session_manager: async_sessionmaker[AsyncSession],
    bad_npi: str,
):
    """`ck_clinicians_npi_format` rejects anything that isn't NULL or
    exactly 10 ASCII digits — defense-in-depth against a wire payload
    that skipped the Pydantic validator."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)

    with pytest.raises(IntegrityError):
        async with db_test_session_manager() as session:
            async with session.begin():
                session.add(_make_clinician(user, npi=bad_npi))


async def test_invalid_license_type_violates_check_constraint(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """`license_type` must be one of `LICENSE_TYPES` — bogus values rejected."""
    user = create_test_user()
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add(user)
            clinician = _make_clinician(user)
            session.add(clinician)
        clinician_id = clinician.id

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
