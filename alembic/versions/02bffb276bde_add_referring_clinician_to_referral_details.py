"""add referring_clinician_id to referral_details

Revision ID: 02bffb276bde
Revises: 958dad6b8606
Create Date: 2026-05-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02bffb276bde"
down_revision: Union[str, None] = "958dad6b8606"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add referring_clinician_id FK column to referral_details."""
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column("referring_clinician_id", sa.Uuid(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_referral_details_referring_clinician_id",
            "clinicians",
            ["referring_clinician_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Remove referring_clinician_id FK column from referral_details."""
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint(
            "fk_referral_details_referring_clinician_id",
            type_="foreignkey",
        )
        batch_op.drop_column("referring_clinician_id")
