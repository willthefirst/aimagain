"""add program_availability post kind

PR 5 of the Org/Program roadmap (#541). Adds ``program_availability_details``
(the per-kind detail table for ``kind='program_availability'``) and widens
the CHECK on ``posts.kind`` to permit the new value alongside
``'client_referral'`` and ``'provider_availability'``. Mirrors
``f4a2c9d18e7b_add_provider_availability_kind.py`` and
``e7b3c2a8f1d4_add_client_referral_kind.py``.

Columns mirror :class:`ProviderAvailabilityDetail` one-to-one — these
are per-announcement attributes (availability slots, featured services,
serving demographics). The Program's name, state preference, intake
window, and owning Org live on :class:`Program` and are dereferenced
via ``program_id``.

``program_id`` cascades on Program delete (matches
``provider_availability_detail.provider_id`` — a post about a deleted
Program is stale by construction).

Schema-only per the repo convention in ``alembic/README.md``.

Revision ID: 73eb6dcb6908
Revises: f89c9e2a7748
Create Date: 2026-05-17 22:15:01.411551

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "73eb6dcb6908"
down_revision: Union[str, None] = "f89c9e2a7748"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. New detail table for the program_availability kind.
    op.create_table(
        "program_availability_details",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "desired_times", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("schedule_text", sa.Text(), nullable=True),
        sa.Column(
            "services", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column(
            "settings", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("treatment_modality", sa.Text(), nullable=True),
        sa.Column(
            "age_groups", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column(
            "languages",
            sa.JSON(),
            server_default=sa.text("'[\"en\"]'"),
            nullable=False,
        ),
        sa.Column("genders", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("referral_instructions", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["program_id"], ["programs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("post_id"),
    )

    # 2. Widen the CHECK on posts.kind. SQLite enforces CHECKs at table
    #    rebuild time, so batch_alter_table is required: drop the old
    #    constraint, recreate with the wider value set. The string is
    #    hard-coded (not sourced from the runtime ``POST_KINDS`` registry)
    #    so a future migration that adds another kind doesn't retroactively
    #    change the SQL this revision installs.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'provider_availability', "
            "'program_availability')",
        )


def downgrade() -> None:
    """Downgrade schema.

    Defensive: reject the downgrade if any ``program_availability`` posts
    exist — the narrower CHECK would silently fail at table rebuild on
    those rows. Mirrors ``f4a2c9d18e7b_add_provider_availability_kind.py``
    and ``e7b3c2a8f1d4_add_client_referral_kind.py``.
    """
    bind = op.get_bind()
    leftover = bind.execute(
        sa.text("SELECT COUNT(*) FROM posts WHERE kind = 'program_availability'")
    ).scalar()
    if leftover:
        raise RuntimeError(
            f"cannot downgrade: {leftover} program_availability post(s) exist; "
            "delete them before downgrading"
        )

    # 1. Drop the detail table.
    op.drop_table("program_availability_details")

    # 2. Restore the narrower CHECK (sans 'program_availability').
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'provider_availability')",
        )
