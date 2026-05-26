"""Add subject to post detail tables

Revision ID: 0a3de87a9217
Revises: ff47c5267ea2
Create Date: 2026-05-25 18:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0a3de87a9217"
down_revision: Union[str, None] = "9e1f7b3c4a2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable subject column to the three post detail tables."""
    for table in ("referral_details", "opening_details", "intake_details"):
        op.add_column(table, sa.Column("subject", sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove subject column from the three post detail tables."""
    for table in ("referral_details", "opening_details", "intake_details"):
        op.drop_column(table, "subject")
