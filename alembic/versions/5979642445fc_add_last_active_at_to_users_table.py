"""Add last_active_at to users table

Revision ID: 5979642445fc
Revises: 00bd09b52ed8
Create Date: 2025-05-26 10:05:47.123456

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5979642445fc"
down_revision: Union[str, None] = "00bd09b52ed8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add last_active_at column to users table."""
    op.add_column(
        "users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Remove last_active_at column from users table."""
    op.drop_column("users", "last_active_at")
