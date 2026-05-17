"""add organizations table

PR 1 of the Org/Program roadmap (#516). Introduces ``organizations`` as
a standalone directory entity; no Provider-side changes yet.

The hierarchy columns are both self-FKs back to ``organizations.id``:

* ``parent_org_id`` — nullable; ``NULL`` for a root.
* ``root_org_id`` — non-nullable; denormalized subtree-root pointer so
  "everything under health-system X" stays a single indexed read.
  For a root, ``root_org_id = id``. The insert-time invariant is
  enforced in the repository — see
  ``src/domain/models/organizations/README.md``.

Schema-only per the repo convention in ``alembic/README.md``. No data
migration needed (the table is new and empty).

Revision ID: a1b2c3d4e5f6
Revises: 9a2b3c4d5e6f
Create Date: 2026-05-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("parent_org_id", sa.Uuid(), nullable=True),
        sa.Column("root_org_id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["root_org_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "type IN ('solo_practice', 'group_practice', 'clinic', "
            "'health_system', 'other')",
            name="ck_organizations_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("organizations")
