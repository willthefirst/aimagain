"""add desired_times JSON columns to per-kind detail tables

Adds the multi-select `desired_times` field from `notes/forms_spec.md`
to both `client_referral_details` and `provider_availability_details`.
Stored as a JSON array of `<day>_<slot>` tokens; vocabulary is enforced
on the wire by the Pydantic `Literal[*DESIRED_TIME_SLOTS]` annotation
rather than a SQL CHECK (CHECK against array members is awkward in
SQLite, and the field is read-once / render-once with no SQL queries
against its members).

Existing rows backfill to an empty list — `desired_times` is optional
on the form, so an empty selection is the natural default.

Revision ID: b8c5e1d4f2a9
Revises: a3f7d92b6c1e
Create Date: 2026-05-05 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c5e1d4f2a9"
down_revision: Union[str, None] = "a3f7d92b6c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ("client_referral_details", "provider_availability_details")


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "desired_times",
                    sa.JSON(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("desired_times")
