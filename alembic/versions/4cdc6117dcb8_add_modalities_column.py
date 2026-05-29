"""add modalities column to all three detail tables

Revision ID: 4cdc6117dcb8
Revises: 02bffb276bde
Create Date: 2026-05-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4cdc6117dcb8"
down_revision: Union[str, None] = "02bffb276bde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add modalities JSON column to referral_details, opening_details, and
    intake_details. Additive: existing rows get an empty-list default and
    are unaffected. The legacy treatment_modality text column is kept as-is.
    """
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "modalities",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            )
        )

    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "modalities",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            )
        )

    with op.batch_alter_table("intake_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "modalities",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            )
        )


def downgrade() -> None:
    """Remove modalities column from all three detail tables."""
    with op.batch_alter_table("intake_details") as batch_op:
        batch_op.drop_column("modalities")

    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.drop_column("modalities")

    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_column("modalities")
