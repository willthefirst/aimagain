"""add provider_availability kind

Adds `provider_availability_details` (the per-kind detail table for
`kind='provider_availability'`) and widens the CHECK on `posts.kind` to
permit the new value alongside `'note'` and `'client_referral'`. MVP
shape: a single `practice_name` column on the detail row.

Revision ID: f4a2c9d18e7b
Revises: e7b3c2a8f1d4
Create Date: 2026-05-05 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a2c9d18e7b"
down_revision: Union[str, None] = "e7b3c2a8f1d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. New detail table for the provider_availability kind.
    op.create_table(
        "provider_availability_details",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("practice_name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )

    # 2. Widen the CHECK on posts.kind. SQLite enforces CHECKs at table
    #    rebuild time, so batch_alter_table is required: drop the old
    #    constraint, recreate with the wider value set.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('note', 'client_referral', 'provider_availability')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Reject the downgrade if any provider_availability posts exist —
    # the narrower CHECK would silently fail at table rebuild on those
    # rows.
    bind = op.get_bind()
    leftover = bind.execute(
        sa.text("SELECT COUNT(*) FROM posts WHERE kind = 'provider_availability'")
    ).scalar()
    if leftover:
        raise RuntimeError(
            f"cannot downgrade: {leftover} provider_availability post(s) exist; "
            "delete them before downgrading"
        )

    # 1. Drop the detail table.
    op.drop_table("provider_availability_details")

    # 2. Restore the narrower CHECK.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind", "kind IN ('note', 'client_referral')"
        )
