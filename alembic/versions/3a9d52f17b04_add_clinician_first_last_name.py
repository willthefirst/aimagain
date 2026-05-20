"""add clinician first_name / last_name columns

Revision ID: 3a9d52f17b04
Revises: 7c3c296c9429
Create Date: 2026-05-20 16:50:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a9d52f17b04"
down_revision: Union[str, None] = "7c3c296c9429"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Both nullable — existing rows predate the columns, backfill is
    # operator-driven, same posture as `clinicians.npi`. The
    # verification pipeline reads the name to score NPPES / OIG
    # matches; nullable here matches the wire schema where both fields
    # are optional.
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.add_column(sa.Column("first_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
