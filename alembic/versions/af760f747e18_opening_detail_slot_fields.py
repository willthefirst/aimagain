"""opening_detail: slot fields

Revision ID: af760f747e18
Revises: b5b6057986f2
Create Date: 2026-05-24 19:09:59.393878

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "af760f747e18"
down_revision: Union[str, None] = "b5b6057986f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    SQLite doesn't support `ADD CONSTRAINT` on an existing table, so we use
    batch mode (copy-and-move) to add the new columns + CHECK constraints in
    one atomic table-recreate. The affiliations NOT NULL alter_columns are
    omitted — SQLite doesn't support ALTER COLUMN and the model already
    enforces NOT NULL at the ORM layer; the autogenerate diff is a false
    positive (same note as T1 migration b5b6057986f2).
    """
    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.add_column(sa.Column("opening_type", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "specialties", sa.JSON(), server_default=sa.text("'[]'"), nullable=False
            )
        )
        batch_op.add_column(
            sa.Column(
                "population_tags",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("fee_low", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("fee_high", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "payment_types",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("availability_state", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("colleague_note", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("note_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "last_confirmed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_opening_details_opening_type",
            "opening_type IN ('individual', 'couples', 'family', 'adolescent', 'group', 'supervision', 'consultation')",
        )
        batch_op.create_check_constraint(
            "ck_opening_details_availability_state",
            "availability_state IN ('taking_now', 'short_wait', 'waitlist', 'not_taking')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("opening_details") as batch_op:
        batch_op.drop_constraint("ck_opening_details_availability_state", type_="check")
        batch_op.drop_constraint("ck_opening_details_opening_type", type_="check")
        batch_op.drop_column("last_confirmed_at")
        batch_op.drop_column("note_expires_at")
        batch_op.drop_column("colleague_note")
        batch_op.drop_column("availability_state")
        batch_op.drop_column("payment_types")
        batch_op.drop_column("fee_high")
        batch_op.drop_column("fee_low")
        batch_op.drop_column("population_tags")
        batch_op.drop_column("specialties")
        batch_op.drop_column("opening_type")
