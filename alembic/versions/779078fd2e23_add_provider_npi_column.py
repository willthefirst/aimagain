"""add provider npi column

Revision ID: 779078fd2e23
Revises: d3f8e1c7b9a2
Create Date: 2026-05-17 21:11:17.552660

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "779078fd2e23"
down_revision: Union[str, None] = "d3f8e1c7b9a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `batch_alter_table` so SQLite picks up both the column add and the
    # named CHECK constraint in one table rewrite. The CHECK mirrors the
    # `_NPI_FORMAT_CHECK` declaration on the `Provider` model — NULL or
    # exactly 10 ASCII digits.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(sa.Column("npi", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_providers_npi_format",
            "npi IS NULL OR (length(npi) = 10 "
            "AND npi GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the CHECK before the column so SQLite's table rewrite stays
    # clean — see `alembic/README.md` §"Dropping a CHECK-constrained
    # column on SQLite".
    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_constraint("ck_providers_npi_format", type_="check")
        batch_op.drop_column("npi")
