"""polymorphic post kinds (client_referral, provider_availability)

Replaces the title/body Post shape with a joined-table-inheritance setup:
the parent `posts` table holds the shared header (owner, timestamps, `kind`
discriminator) and each kind owns a child table keyed by `id` FK back to
`posts.id` (cascade on delete).

Drop-and-recreate is the recovery path for any pre-existing rows — plain
title/body posts are not preserved.

Revision ID: c4f9a8b21d34
Revises: 8a6ada1e0883
Create Date: 2026-05-02 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4f9a8b21d34"
down_revision: Union[str, None] = "8a6ada1e0883"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the old `posts` table; recreate as a polymorphic parent and add
    `client_referrals` + `provider_availabilities` child tables."""
    op.drop_table("posts")
    op.create_table(
        "posts",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('client_referral','provider_availability')",
            name="posts_kind_check",
        ),
    )
    # Child tables for joined-table inheritance — only `id` (PK + FK to
    # `posts.id`). Timestamps and other shared fields live on the parent
    # table; SQLAlchemy reads them via the JTI join.
    op.create_table(
        "client_referrals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "provider_availabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Reverse upgrade: drop child tables, drop polymorphic posts, restore the
    original title/body shape."""
    op.drop_table("provider_availabilities")
    op.drop_table("client_referrals")
    op.drop_table("posts")
    op.create_table(
        "posts",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
