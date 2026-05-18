"""add provider.org_id column (nullable)

PR 2 of the Org/Program roadmap (#520), schema half. Adds
``providers.org_id`` as a nullable FK to ``organizations.id``. The
column is intentionally nullable here — the data backfill that
populates every existing row, then promotes the column to ``NOT NULL``,
lives in the follow-up data migration ``c2e0b4d6f8a3``.

Per ``alembic/README.md``: schema-only here, data backfill is a
separate file. Splitting the two keeps each migration small and
reviewable; the backfill knows it can `SELECT` from a stable schema.

Revision ID: b1f9a3c5d7e2
Revises: a1b2c3d4e5f6
Create Date: 2026-05-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1f9a3c5d7e2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "providers"
_FK_NAME = "fk_providers_org_id_organizations"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.add_column(sa.Column("org_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            _FK_NAME,
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.drop_column("org_id")
