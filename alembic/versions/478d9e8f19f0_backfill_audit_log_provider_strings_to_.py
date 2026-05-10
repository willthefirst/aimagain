"""backfill audit_log provider strings to provider

Closes the rename drift left by `9f1a8b2c3d4e` (which renamed the
`provider_profiles` table to `providers` but intentionally left the
audit-log persisted strings alone). Rewrites
`audit_log.resource_type = 'provider_profile'` → `'provider'` and the
three matching `action` values (`create_provider_profile` →
`create_provider`, etc.).

Pure data migration — no schema change. Reversible: the downgrade
rewrites the same rows back to the old strings. `UPDATE` of zero rows
is a no-op, so this is safe against a fresh DB with no provider audit
rows yet.

Revision ID: 478d9e8f19f0
Revises: 9f1a8b2c3d4e
Create Date: 2026-05-10 12:23:09.995780

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "478d9e8f19f0"
down_revision: Union[str, None] = "9f1a8b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTION_RENAMES = (
    ("create_provider_profile", "create_provider"),
    ("update_provider_profile", "update_provider"),
    ("delete_provider_profile", "delete_provider"),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE audit_log SET resource_type = :new " "WHERE resource_type = :old"
        ),
        {"old": "provider_profile", "new": "provider"},
    )
    for old, new in _ACTION_RENAMES:
        bind.execute(
            sa.text("UPDATE audit_log SET action = :new WHERE action = :old"),
            {"old": old, "new": new},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for old, new in _ACTION_RENAMES:
        bind.execute(
            sa.text("UPDATE audit_log SET action = :old WHERE action = :new"),
            {"old": old, "new": new},
        )
    bind.execute(
        sa.text(
            "UPDATE audit_log SET resource_type = :old " "WHERE resource_type = :new"
        ),
        {"old": "provider_profile", "new": "provider"},
    )
