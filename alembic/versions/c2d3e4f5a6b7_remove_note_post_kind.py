"""remove note post kind

Drops the now-defunct `note` post kind: deletes any existing posts of
`kind='note'` (their `note_details` rows go via the FK CASCADE), drops
the `note_details` table itself, and narrows the CHECK on `posts.kind`
to the remaining kinds (`client_referral`, `provider_availability`).

Revision ID: c2d3e4f5a6b7
Revises: f4a2c9d18e7b
Create Date: 2026-05-05 22:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "f4a2c9d18e7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop existing note posts. The FK CASCADE on note_details.post_id
    #    removes the matching detail rows.
    op.execute("DELETE FROM posts WHERE kind = 'note'")

    # 2. Drop the note_details table.
    op.drop_table("note_details")

    # 3. Narrow the CHECK on posts.kind. SQLite enforces CHECKs at table
    #    rebuild time, so batch_alter_table is required.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'provider_availability')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Widen the CHECK back to include 'note'.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('note', 'client_referral', 'provider_availability')",
        )

    # 2. Recreate the note_details table. Pre-existing note posts cannot
    #    be recovered — they were deleted on upgrade — so the table comes
    #    back empty.
    op.create_table(
        "note_details",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )
