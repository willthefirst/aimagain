"""Retarget all provider_id FKs to clinicians; add clinicians.owner_id

Part 1 of dropping the `providers` table. `providers` was a thin join
table (owner_id → users, clinician_id → clinicians). This migration
moves owner_id onto clinicians directly and retargets every table that
previously FK'd to providers.id so that they point at clinicians.id.

Tables changed:
  - clinicians:      add owner_id (FK → users.id)
  - affiliations:    drop provider_id (clinician_id already present)
  - user_favorites:  provider_id → clinician_id (FK → clinicians.id)
  - verifications:   provider_id → clinician_id (FK → clinicians.id)
  - opening_details: provider_id → clinician_id (FK → clinicians.id)

NOTE: intended to run on an empty DB (dev-only). Drop and recreate is
used for tables where the FK target changes — simplest for SQLite.

Revision ID: b5d2e8f1a3c9
Revises: 0a3de87a9217
Create Date: 2026-05-26
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b5d2e8f1a3c9"
down_revision: Union[str, None] = "0a3de87a9217"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("PRAGMA foreign_keys = OFF"))

    # 1. clinicians: add owner_id
    # Use batch_alter_table so SQLite's copy-and-move strategy handles
    # the FK constraint (op.add_column with ForeignKey raises
    # NotImplementedError on SQLite).
    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_clinicians_owner_id", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )

    # 2. affiliations: drop provider_id (clinician_id + org_id already there)
    with op.batch_alter_table("affiliations") as batch_op:
        batch_op.drop_column("provider_id")

    # 3. user_favorites: drop and recreate with clinician_id
    op.drop_table("user_favorites")
    op.create_table(
        "user_favorites",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "user_id", "clinician_id", name="uq_user_favorites_user_clinician"
        ),
        sa.Index("ix_user_favorites_user_id_created_at", "user_id", "created_at"),
    )

    # 4. verifications: drop and recreate with clinician_id
    op.drop_table("verifications")
    op.create_table(
        "verifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "flags",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("nppes_result", sa.JSON(), nullable=True),
        sa.Column(
            "oig_match",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("name_match_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('verified','needs_review','failed')",
            name="ck_verifications_status",
        ),
    )

    # 5. opening_details: drop and recreate with clinician_id
    op.drop_table("opening_details")
    op.create_table(
        "opening_details",
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "desired_times",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("schedule_text", sa.Text(), nullable=True),
        sa.Column(
            "services",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "settings",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("treatment_modality", sa.Text(), nullable=True),
        sa.Column(
            "age_groups",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "languages",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"en\"]'"),
        ),
        sa.Column(
            "genders",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("referral_instructions", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
    )

    bind.execute(sa.text("PRAGMA foreign_keys = ON"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("PRAGMA foreign_keys = OFF"))

    # Reverse: recreate tables with provider_id
    op.drop_table("opening_details")
    op.create_table(
        "opening_details",
        sa.Column(
            "post_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "desired_times", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("schedule_text", sa.Text(), nullable=True),
        sa.Column(
            "services", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "settings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("treatment_modality", sa.Text(), nullable=True),
        sa.Column(
            "age_groups", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "languages",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"en\"]'"),
        ),
        sa.Column("genders", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("referral_instructions", sa.Text(), nullable=True),
        sa.Column("website", sa.Text(), nullable=True),
    )

    op.drop_table("verifications")
    op.create_table(
        "verifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("nppes_result", sa.JSON(), nullable=True),
        sa.Column(
            "oig_match", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("name_match_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('verified','needs_review','failed')",
            name="ck_verifications_status",
        ),
    )

    op.drop_table("user_favorites")
    op.create_table(
        "user_favorites",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "user_id", "provider_id", name="uq_user_favorites_user_provider"
        ),
        sa.Index("ix_user_favorites_user_id_created_at", "user_id", "created_at"),
    )

    with op.batch_alter_table("affiliations") as batch_op:
        batch_op.add_column(
            sa.Column("provider_id", sa.Uuid(as_uuid=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_affiliations_provider_id",
            "providers",
            ["provider_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("clinicians") as batch_op:
        batch_op.drop_column("owner_id")

    bind.execute(sa.text("PRAGMA foreign_keys = ON"))
