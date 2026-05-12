"""relax_pa_required_fields

Revision ID: bf8725bca464
Revises: 5b2d97b1860f
Create Date: 2026-05-11 22:11:44.350836

#433: relax four `provider_availability_details` columns from
`NOT NULL` to nullable. Telehealth-only practices (Katie Reeves) have
no usable city/ZIP; some posts will plausibly want to leave
in_person/virtual session-format unspecified.

`services` and `settings` columns stay `NOT NULL DEFAULT '[]'` — only
the wire validator drops `min_length=1`.

Downgrade caveat: if any row has NULL in any of the four columns when
this revision is reversed, the back-to-NOT-NULL alter will fail.
Backfill before downgrading.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bf8725bca464"
down_revision: Union[str, None] = "5b2d97b1860f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Nullability flips for four columns; SQLite needs
    batch mode (table rewrite) to alter column constraints."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.alter_column("location_city", existing_type=sa.TEXT(), nullable=True)
        batch_op.alter_column("location_zip", existing_type=sa.TEXT(), nullable=True)
        batch_op.alter_column(
            "in_person_sessions", existing_type=sa.TEXT(), nullable=True
        )
        batch_op.alter_column(
            "virtual_sessions", existing_type=sa.TEXT(), nullable=True
        )


def downgrade() -> None:
    """Downgrade schema.

    Fails if any row has NULL in the affected columns. Backfill first.
    """
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.alter_column("location_city", existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column("location_zip", existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column(
            "in_person_sessions", existing_type=sa.TEXT(), nullable=False
        )
        batch_op.alter_column(
            "virtual_sessions", existing_type=sa.TEXT(), nullable=False
        )
