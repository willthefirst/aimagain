"""client_referral basic fields (summary, urgency, region)

Adds three NOT NULL columns to `client_referrals`. Existing rows are
disposable — `dev down --volumes` is the recovery path — so the migration
adds NOT NULL columns directly without a default-then-backfill dance.

Revision ID: e7a91d2c5b86
Revises: c4f9a8b21d34
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e7a91d2c5b86"
down_revision: Union[str, None] = "c4f9a8b21d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add summary/urgency/region to `client_referrals`."""
    with op.batch_alter_table("client_referrals") as batch_op:
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("urgency", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("region", sa.Text(), nullable=False))
        batch_op.create_check_constraint(
            "client_referrals_urgency_check",
            "urgency IN ('low','medium','high')",
        )


def downgrade() -> None:
    with op.batch_alter_table("client_referrals") as batch_op:
        batch_op.drop_constraint("client_referrals_urgency_check", type_="check")
        batch_op.drop_column("region")
        batch_op.drop_column("urgency")
        batch_op.drop_column("summary")
