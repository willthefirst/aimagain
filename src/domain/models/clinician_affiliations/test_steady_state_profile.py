"""Tests for the steady-state profile columns added to
:class:`ClinicianAffiliation` in #1358 PR-f sub-1.

The eight new columns (``services`` / ``settings`` / ``modalities`` /
``age_groups`` / ``genders`` / ``website`` / ``referral_instructions``
/ ``currently_accepting_new_patients``) are the per-affiliation home
for what used to live on ``OpeningDetail`` — the move is what the
#1358 PR-f sub-sequence reshapes. The matching person-level move
(``languages`` → :class:`Clinician`) is covered in
``../clinicians/test_clinician_steady_state_profile.py``.

These tests pin the schema-level defaults so the next sub-PR can
flip reads onto these columns without re-discovering "what does an
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


async def test_new_profile_columns_default_to_empty(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A freshly constructed ``ClinicianAffiliation`` (no kwargs for the
    new columns) persists with empty lists / NULL text / False bool.
    These defaults mirror the prior ``OpeningDetail`` shape so that the
    backfill migration only has to copy non-empty values and the
    "no-existing-openings" affiliations land in a self-consistent
    state."""
    user = _user("alice")
    clinician = _clinician(user)
    affiliation = ClinicianAffiliation(clinician=clinician)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(ClinicianAffiliation))).scalars().one()
        assert row.services == []
        assert row.settings == []
        assert row.modalities == []
        assert row.age_groups == []
        assert row.genders == []
        assert row.website is None
        assert row.referral_instructions is None
        assert row.currently_accepting_new_patients is False
    _ = affiliation  # transient instance produced by Clinician auto-create


async def test_profile_columns_round_trip_assigned_values(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Setting non-default values persists them verbatim. JSON list
    columns store arbitrary JSON arrays — vocabulary enforcement lives
    on the wire (Pydantic ``Literal[...]``), same pattern as the
    existing ``in_network_carriers`` column."""
    user = _user("bob")
    clinician = _clinician(user)
    affiliation = ClinicianAffiliation(clinician=clinician)
    affiliation.services = ["medication_management", "psychotherapy"]
    affiliation.settings = ["outpatient"]
    affiliation.modalities = ["cbt", "emdr"]
    affiliation.age_groups = ["adults", "older_adults"]
    affiliation.genders = ["female", "non_binary"]
    affiliation.website = "https://example.com/practice"
    affiliation.referral_instructions = "Email referrals to intake@example.com"
    affiliation.currently_accepting_new_patients = True

    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(ClinicianAffiliation))).scalars().one()
        assert row.services == ["medication_management", "psychotherapy"]
        assert row.settings == ["outpatient"]
        assert row.modalities == ["cbt", "emdr"]
        assert row.age_groups == ["adults", "older_adults"]
        assert row.genders == ["female", "non_binary"]
        assert row.website == "https://example.com/practice"
        assert row.referral_instructions == "Email referrals to intake@example.com"
        assert row.currently_accepting_new_patients is True
