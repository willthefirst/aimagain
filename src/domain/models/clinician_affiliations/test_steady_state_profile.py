"""Tests for the steady-state how-to-refer columns on
:class:`ClinicianAffiliation`.

After the steady-state remodel the per-announcement profile fields
(``services`` / ``settings`` / ``modalities`` / ``age_groups`` /
``genders`` / ``cost`` / delivery format) live on ``OpeningDetail`` (the
opening post), not here. What remains on the affiliation is the
steady-state how-to-refer surface: ``website`` /
``referral_instructions`` and the denormalized
``currently_accepting_new_patients`` cache.

These tests pin the column-level defaults so the next sub-PR can flip
reads onto these columns without re-discovering "what does an
unbackfilled row look like".
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, ClinicianAffiliation, User

pytestmark = pytest.mark.asyncio


def _user(username: str) -> User:
    return User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@example.com",
        hashed_password="not-a-password",
        is_active=True,
        is_verified=True,
    )


def _clinician(owner: User) -> Clinician:
    return Clinician(
        owner_id=owner.id,
        first_name="Jane",
        last_name="Smith",
    )


async def test_how_to_refer_columns_default_to_empty(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A freshly constructed ``ClinicianAffiliation`` (no kwargs for the
    how-to-refer columns) persists with NULL text and a False
    ``currently_accepting_new_patients`` cache."""
    user = _user("alice")
    clinician = _clinician(user)
    affiliation = ClinicianAffiliation(clinician=clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(ClinicianAffiliation))).scalars().one()
        assert row.website is None
        assert row.referral_instructions is None
        assert row.currently_accepting_new_patients is False
    _ = affiliation  # transient instance produced by Clinician auto-create


async def test_how_to_refer_columns_round_trip_assigned_values(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Setting non-default values persists them verbatim."""
    user = _user("bob")
    clinician = _clinician(user)
    affiliation = ClinicianAffiliation(clinician=clinician)
    affiliation.website = "https://example.com/practice"
    affiliation.referral_instructions = "Email referrals to intake@example.com"
    affiliation.currently_accepting_new_patients = True

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(ClinicianAffiliation))).scalars().one()
        assert row.website == "https://example.com/practice"
        assert row.referral_instructions == "Email referrals to intake@example.com"
        assert row.currently_accepting_new_patients is True
