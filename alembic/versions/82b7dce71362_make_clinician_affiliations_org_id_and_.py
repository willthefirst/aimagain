"""make clinician_affiliations.org_id and sessions nullable

Enables the "solo clinician" practice posture container — a clinician
with no LLC / no group affiliation gets a ``ClinicianAffiliation`` row
whose ``org_id`` IS NULL. The row still carries the per-affiliation
posture columns (location, availability, insurance, cost). Sessions
columns also become nullable so a stub affiliation auto-created at
verify time can land before the user has been asked the in-person /
virtual questions.

SQLite needs ``batch_alter_table`` for ``ALTER COLUMN`` (see
``alembic/README.md``) — bare ``op.alter_column`` fails with
``near "ALTER": syntax error`` because SQLite has no native ALTER
COLUMN. Batch mode rewrites the table cleanly.

The CHECK constraints on ``in_person_sessions`` / ``virtual_sessions``
already permit NULL: ``column IN (values)`` evaluates to NULL on a
NULL input rather than False, so NULL bypasses the check (standard
SQL semantics). No CHECK rewriting needed.

The companion data migration backfills a stub affiliation for every
existing clinician with zero affiliations.

Revision ID: 82b7dce71362
Revises: 9a4f1c7e0a21
Create Date: 2026-06-10 09:59:08.659965

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82b7dce71362"
down_revision: Union[str, None] = "9a4f1c7e0a21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen three columns from NOT NULL to NULL."""
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.alter_column(
            "org_id",
            existing_type=sa.CHAR(length=32),
            nullable=True,
        )
        batch_op.alter_column(
            "in_person_sessions",
            existing_type=sa.TEXT(),
            nullable=True,
        )
        batch_op.alter_column(
            "virtual_sessions",
            existing_type=sa.TEXT(),
            nullable=True,
        )


def downgrade() -> None:
    """Restore NOT NULL. Will fail if any row has a NULL in one of these
    columns — that's the expected behavior: downgrading past the stub-
    affiliation invariant requires either deleting those rows or
    assigning real values first.
    """
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.alter_column(
            "virtual_sessions",
            existing_type=sa.TEXT(),
            nullable=False,
        )
        batch_op.alter_column(
            "in_person_sessions",
            existing_type=sa.TEXT(),
            nullable=False,
        )
        batch_op.alter_column(
            "org_id",
            existing_type=sa.CHAR(length=32),
            nullable=False,
        )
