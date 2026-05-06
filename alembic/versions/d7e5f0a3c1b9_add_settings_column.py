"""add settings JSON column to provider_availability_details

Adds the multi-select `settings` field from `notes/forms_spec.md` Form 2
to `provider_availability_details` only. Stored as a JSON array of
`TREATMENT_SETTINGS` tokens (outpatient, iop, crisis_care, php,
residential); vocabulary is enforced on the wire by Pydantic, mirroring
the `services` and `desired_times` column shapes. Same rationale: SQL
CHECKs against JSON-array members are awkward in SQLite, and the field
is read-once / render-once with no SQL queries against its members.

Existing rows backfill to `[]`. The `provider_availability` schema
enforces min-1 on Create/Update at the Pydantic layer; backfilled `[]`
rows are still readable (Read / AuditSnapshot don't enforce min-1) and
remain editable as long as a PATCH doesn't explicitly send `settings: []`.

Revision ID: d7e5f0a3c1b9
Revises: c4f8b1a9d62e
Create Date: 2026-05-06 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e5f0a3c1b9"
down_revision: Union[str, None] = "c4f8b1a9d62e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "settings",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_column("settings")
