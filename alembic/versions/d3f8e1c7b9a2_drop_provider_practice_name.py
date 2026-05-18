"""drop providers.practice_name

PR 3 of the Org/Program roadmap (#524). The denormalized
``providers.practice_name`` mirror introduced in PR 2 (#520) is removed
now that every reader has switched to ``provider.org.name``.
``Provider.org_id`` (NOT NULL since the backfill in ``c2e0b4d6f8a3``)
becomes the sole source of truth for the practice's display name via
``Organization.name``.

The downgrade adds the column back as **nullable** — a real downgrade
cannot repopulate per-row ``practice_name`` values from the database
alone without re-running the join to ``organizations``. Operators
restoring this column should run a one-shot ``UPDATE providers SET
practice_name = (SELECT name FROM organizations WHERE id =
providers.org_id)`` after the downgrade, then promote to NOT NULL.

Revision ID: d3f8e1c7b9a2
Revises: c2e0b4d6f8a3
Create Date: 2026-05-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d3f8e1c7b9a2"
down_revision: Union[str, None] = "c2e0b4d6f8a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_column("practice_name")


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(sa.Column("practice_name", sa.Text(), nullable=True))
