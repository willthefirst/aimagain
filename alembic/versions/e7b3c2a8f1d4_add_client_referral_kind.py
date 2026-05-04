"""add client_referral kind

Adds `client_referral_details` (the per-kind detail table for
`kind='client_referral'`) and widens the CHECK on `posts.kind` to permit
the new value alongside `'note'`. MVP shape: a single `description`
column on the detail row.

Revision ID: e7b3c2a8f1d4
Revises: c1a4f0b3e2d1
Create Date: 2026-05-04 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b3c2a8f1d4"
down_revision: Union[str, None] = "c1a4f0b3e2d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. New detail table for the client_referral kind.
    op.create_table(
        "client_referral_details",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )

    # 2. Widen the CHECK on posts.kind. SQLite enforces CHECKs at table
    #    rebuild time, so batch_alter_table is required: drop the old
    #    constraint, recreate with the wider value set.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind", "kind IN ('note', 'client_referral')"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Reject the downgrade if any client_referral posts exist — the
    # narrower CHECK would silently fail at table rebuild on those rows.
    bind = op.get_bind()
    leftover = bind.execute(
        sa.text("SELECT COUNT(*) FROM posts WHERE kind = 'client_referral'")
    ).scalar()
    if leftover:
        raise RuntimeError(
            f"cannot downgrade: {leftover} client_referral post(s) exist; "
            "delete them before downgrading"
        )

    # 1. Drop the detail table.
    op.drop_table("client_referral_details")

    # 2. Restore the narrower CHECK.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint("ck_posts_kind", "kind IN ('note')")
