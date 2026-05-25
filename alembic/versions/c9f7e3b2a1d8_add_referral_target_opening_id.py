"""add referral target_opening_id

Revision ID: c9f7e3b2a1d8
Revises: af760f747e18
Create Date: 2026-05-24 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9f7e3b2a1d8"
down_revision: Union[str, None] = "a1b9c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable target_opening_id column to referral_details.

    Uses batch mode (copy-and-move) because SQLite doesn't support ADD COLUMN
    with a UUID type in a single ALTER — batch mode recreates the table with
    the new column in place.
    """
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column("target_opening_id", sa.Uuid(as_uuid=True), nullable=True)
        )


def downgrade() -> None:
    """Drop target_opening_id from referral_details."""
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_column("target_opening_id")
