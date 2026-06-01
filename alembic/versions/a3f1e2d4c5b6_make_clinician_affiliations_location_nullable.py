"""make clinician_affiliations location columns nullable

Revision ID: a3f1e2d4c5b6
Revises: 9b078396f8f2
Create Date: 2026-06-01 00:00:00.000000

Location (city / state / zip) on clinician_affiliations becomes nullable
so the onboarding wizard can collect only name + NPI on the fast path
and let users fill in location later from the "complete your profile"
section.  referral_details.location_* stays NOT NULL — a referral is
always tied to a client location.

The location_state CHECK constraint is dropped and re-created to allow
NULL.  SQL NULL passes CHECK constraints by default, but we add an
explicit ``IS NULL OR`` arm so the intent is readable and future
contributors don't remove it thinking it's redundant.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f1e2d4c5b6"
down_revision: Union[str, None] = "9b078396f8f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATES_SQL = (
    "location_state IS NULL OR location_state IN "
    "('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', "
    "'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', "
    "'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', "
    "'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', "
    "'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')"
)

_STATES_SQL_NOT_NULL = (
    "location_state IN "
    "('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', "
    "'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', "
    "'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', "
    "'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', "
    "'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')"
)


def upgrade() -> None:
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.drop_constraint(
            "ck_clinician_affiliations_location_state", type_="check"
        )
        batch_op.alter_column("location_city", nullable=True, type_=sa.Text())
        batch_op.alter_column("location_state", nullable=True, type_=sa.Text())
        batch_op.alter_column("location_zip", nullable=True, type_=sa.Text())
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_location_state",
            _STATES_SQL,
        )


def downgrade() -> None:
    # Pre-launch: any NULL location rows would violate the restored NOT NULL
    # constraint.  Caller must backfill or delete such rows before running
    # downgrade in a non-empty database.
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.drop_constraint(
            "ck_clinician_affiliations_location_state", type_="check"
        )
        batch_op.alter_column("location_city", nullable=False, type_=sa.Text())
        batch_op.alter_column("location_state", nullable=False, type_=sa.Text())
        batch_op.alter_column("location_zip", nullable=False, type_=sa.Text())
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_location_state",
            _STATES_SQL_NOT_NULL,
        )
