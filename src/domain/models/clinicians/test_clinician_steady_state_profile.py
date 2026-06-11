"""Tests for the steady-state profile columns added in #1358 PR-f sub-1.

The relevant addition on :class:`Clinician` is ``languages`` — the
person-level move of the field that used to live on ``OpeningDetail``.
The matching fields on the per-affiliation side live on
:class:`ClinicianAffiliation` and are covered in
``../clinician_affiliations/test_steady_state_profile.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Clinician, User

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


def _clinician(owner: User, **overrides) -> Clinician:
    defaults = dict(
        owner_id=owner.id,
        first_name="Jane",
        last_name="Smith",
    )
    defaults.update(overrides)
    return Clinician(**defaults)


async def test_languages_defaults_to_english_when_unset(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """``Clinician.languages`` server-defaults to ``["en"]`` — every
    persisted clinician comes out the other side with at least one
    language so reads can iterate the list without a None guard. Same
    shape the column had on ``OpeningDetail`` before the move."""
    user = _user("alice")
    clinician = _clinician(user)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(Clinician))).scalars().one()
        assert row.languages == ["en"]


async def test_languages_round_trips_assigned_list(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A non-default value persists verbatim. Vocabulary enforcement
    lives on the wire (Pydantic ``Literal[*LANGUAGES]``); the column
    itself stores any JSON list — same pattern as
    ``Clinician.affirming_identities``."""
    user = _user("bob")
    clinician = _clinician(user, languages=["en", "es", "zh"])
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(Clinician))).scalars().one()
        assert row.languages == ["en", "es", "zh"]


async def test_languages_accepts_empty_list_when_explicit(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Empty list is a valid persisted value — used at backfill time
    when an existing OpeningDetail had ``languages = []``. Distinct
    from the default applied to fresh rows (``["en"]``); the column
    is NOT NULL but does not constrain length."""
    user = _user("carol")
    clinician = _clinician(user, languages=[])
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, clinician])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(Clinician))).scalars().one()
        assert row.languages == []
