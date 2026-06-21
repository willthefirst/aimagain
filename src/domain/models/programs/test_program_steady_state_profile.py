"""Tests for the steady-state context columns on :class:`Program`.

The per-announcement profile (services / settings / modalities /
age_groups / genders) moved off ``Program`` onto ``IntakeDetail``.
What remains here is the steady-state context that doesn't vary per
intake window: ``languages``, ``website``, ``referral_instructions``,
and the ``currently_accepting_new_patients`` lifecycle-cache flag —
distinct from the standing ``accepting_referrals`` posture.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.models import Program
from tests.helpers import create_test_user, make_organization_row

pytestmark = pytest.mark.asyncio


def _make_program(*, owner_id: uuid.UUID, org_id: uuid.UUID, **overrides) -> Program:
    defaults = dict(name="RISE IOP")
    defaults.update(overrides)
    return Program(owner_id=owner_id, org_id=org_id, **defaults)


async def test_context_columns_default(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """A freshly created Program lands with ``["en"]`` languages, NULL
    free-text, and ``currently_accepting_new_patients`` False.
    ``accepting_referrals`` stays at its own default of True — these
    two are deliberately distinct: the standing operator posture vs.
    the lifecycle-cache flag."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, org])
            session.add(_make_program(owner_id=user.id, org_id=org.id))

    async with db_test_session_manager() as session:
        row = (await session.execute(select(Program))).scalars().one()
        assert row.languages == ["en"]
        assert row.website is None
        assert row.referral_instructions is None
        assert row.currently_accepting_new_patients is False
        # The pre-existing posture flag stays at its True default —
        # distinct from the new lifecycle cache above.
        assert row.accepting_referrals is True


async def test_context_columns_round_trip_assigned_values(
    db_test_session_manager: async_sessionmaker[AsyncSession],
):
    """Non-default values persist verbatim across the context columns."""
    user = create_test_user()
    org = make_organization_row(owner_id=user.id)
    program = _make_program(
        owner_id=user.id,
        org_id=org.id,
        languages=["en", "zh"],
        website="https://example.com/program",
        referral_instructions="See website for intake form.",
        currently_accepting_new_patients=True,
    )
    async with db_test_session_manager() as session:
        async with session.begin():
            session.add_all([user, org, program])

    async with db_test_session_manager() as session:
        row = (await session.execute(select(Program))).scalars().one()
        assert row.languages == ["en", "zh"]
        assert row.website == "https://example.com/program"
        assert row.referral_instructions == "See website for intake form."
        assert row.currently_accepting_new_patients is True
