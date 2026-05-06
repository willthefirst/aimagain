"""add services JSON columns to per-kind detail tables

Adds the multi-select `services` field from `notes/forms_spec.md` to
both `client_referral_details` and `provider_availability_details`.
Stored as a JSON array of `CLIENT_REFERRAL_SERVICES` tokens; vocabulary
is enforced on the wire by Pydantic, mirroring the `desired_times`
column shape (see `b8c5e1d4f2a9`). Same rationale: SQL CHECKs against
JSON-array members are awkward in SQLite, and the field is read-once /
render-once with no SQL queries against its members.

Existing rows backfill to `[]` on both tables. `client_referral`'s
`services` is wire-optional so empty is its natural default. The
`provider_availability` schema enforces min-1 on Create/Update at the
Pydantic layer; backfilled `[]` rows are still readable (Read /
AuditSnapshot don't enforce min-1) and remain editable as long as a
PATCH doesn't explicitly send `services: []`. Refusing the upgrade on
existing PA rows would be more conservative, but there is no PA data
in production yet — when there is, the wire-level invariant is the
operative one and the column-default story is symmetric across both
tables.

Revision ID: c4f8b1a9d62e
Revises: b8c5e1d4f2a9
Create Date: 2026-05-06 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f8b1a9d62e"
down_revision: Union[str, None] = "b8c5e1d4f2a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = ("client_referral_details", "provider_availability_details")


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "services",
                    sa.JSON(),
                    server_default=sa.text("'[]'"),
                    nullable=False,
                )
            )


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("services")
