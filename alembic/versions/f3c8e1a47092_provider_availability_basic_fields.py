"""provider_availability basic fields (specialty, region, accepting_new_clients)

Adds three NOT NULL columns to `provider_availabilities`. Existing rows
are disposable — `dev down --volumes` is the recovery path — so the
migration adds NOT NULL columns directly without a default-then-backfill
dance.

Revision ID: f3c8e1a47092
Revises: e7a91d2c5b86
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f3c8e1a47092"
down_revision: Union[str, None] = "e7a91d2c5b86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add specialty/region/accepting_new_clients to `provider_availabilities`."""
    with op.batch_alter_table("provider_availabilities") as batch_op:
        batch_op.add_column(sa.Column("specialty", sa.Text(), nullable=False))
        batch_op.add_column(sa.Column("region", sa.Text(), nullable=False))
        batch_op.add_column(
            sa.Column("accepting_new_clients", sa.Boolean(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_availabilities") as batch_op:
        batch_op.drop_column("accepting_new_clients")
        batch_op.drop_column("region")
        batch_op.drop_column("specialty")
