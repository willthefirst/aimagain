"""add user.onboarding_intent

Revision ID: b5b6057986f2
Revises: 9e1f7b3c4a2d
Create Date: 2026-05-24 17:19:59.173919

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5b6057986f2"
down_revision: Union[str, None] = "9e1f7b3c4a2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    SQLite doesn't support `ADD CONSTRAINT` on an existing table, so we use
    batch mode (copy-and-move) to add the column + CHECK in one atomic
    table-recreate. The affiliations NOT NULL alter_columns are omitted —
    SQLite doesn't support ALTER COLUMN and the model already enforces NOT
    NULL at the ORM layer; the autogenerate diff is a false positive.
    """
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("onboarding_intent", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_users_onboarding_intent",
            "onboarding_intent IN ('refer_now', 'have_openings', 'invited', 'building_network')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_onboarding_intent", type_="check")
        batch_op.drop_column("onboarding_intent")
