"""post parent + note detail

Splits `posts` into a parent table (id, kind, owner, timestamps) and a
per-kind detail table `note_details` (post_id PK+FK, title, body). All
existing posts become `kind='note'`; their title/body move to the detail
row keyed by post_id.

Revision ID: c1a4f0b3e2d1
Revises: 8a6ada1e0883
Create Date: 2026-05-03 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a4f0b3e2d1"
down_revision: Union[str, None] = "8a6ada1e0883"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. New detail table.
    op.create_table(
        "note_details",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )

    # 2. Add `kind` to posts as nullable so we can backfill before adding
    #    the NOT NULL + CHECK.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.Text(), nullable=True))

    # 3. Backfill: copy title/body into note_details, set kind='note' on
    #    every existing post.
    op.execute(
        "INSERT INTO note_details (post_id, title, body) "
        "SELECT id, title, body FROM posts"
    )
    op.execute("UPDATE posts SET kind = 'note'")

    # 4. Lock down the new shape: NOT NULL + CHECK on kind, drop the now
    #    redundant title/body columns.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.alter_column("kind", existing_type=sa.Text(), nullable=False)
        batch_op.create_check_constraint("ck_posts_kind", "kind IN ('note')")
        batch_op.drop_column("title")
        batch_op.drop_column("body")


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Re-add title/body as nullable so we can backfill from note_details.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.add_column(sa.Column("title", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("body", sa.Text(), nullable=True))

    # 2. Backfill from note_details.
    op.execute(
        "UPDATE posts SET "
        "title = (SELECT title FROM note_details WHERE post_id = posts.id), "
        "body = (SELECT body FROM note_details WHERE post_id = posts.id)"
    )

    # 3. Lock title/body back down, drop kind constraint+column.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.alter_column("title", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("body", existing_type=sa.Text(), nullable=False)
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.drop_column("kind")

    # 4. Drop the detail table.
    op.drop_table("note_details")
