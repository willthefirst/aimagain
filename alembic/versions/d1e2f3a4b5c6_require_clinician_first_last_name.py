"""Require clinician first_name and last_name (NOT NULL)

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9
Create Date: 2026-06-06 00:00:00.000000

`Clinician.first_name` and `Clinician.last_name` were nullable at creation
but are always required in practice — every clinician-authored post kind
surfaces the provider's name. Existing NULL rows (dev/test data) are
backfilled with 'Unknown' before the constraint is applied.
"""

from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE clinicians SET first_name = 'Unknown' WHERE first_name IS NULL")
    op.execute("UPDATE clinicians SET last_name = 'Unknown' WHERE last_name IS NULL")
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.alter_column("first_name", nullable=False)
        batch_op.alter_column("last_name", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.alter_column("first_name", nullable=True)
        batch_op.alter_column("last_name", nullable=True)
