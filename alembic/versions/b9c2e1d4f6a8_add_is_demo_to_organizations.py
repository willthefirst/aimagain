"""Add is_demo flag to organizations

Revision ID: b9c2e1d4f6a8
Revises: a3f1e2d4c5b6
Create Date: 2026-06-01 00:00:00.000000

`is_demo` marks an organization as a demonstration environment. Clinicians
and organizations in demo orgs bypass real NPPES/OIG verification and let
users select a simulated verification outcome from the profile hub instead
of calling external APIs.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b9c2e1d4f6a8"
down_revision: Union[str, None] = "a3f1e2d4c5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_demo",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch_op:
        batch_op.drop_column("is_demo")
