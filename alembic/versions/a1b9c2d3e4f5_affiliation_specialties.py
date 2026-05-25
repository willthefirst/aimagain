"""affiliation.specialties — JSON list for be-findable wizard step

Revision ID: a1b9c2d3e4f5
Revises: b5b6057986f2
Create Date: 2026-05-24 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a1b9c2d3e4f5"
down_revision: Union[str, None] = "b5b6057986f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("affiliations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "specialties",
                sa.JSON(),
                nullable=False,
                server_default="'[]'",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("affiliations") as batch_op:
        batch_op.drop_column("specialties")
