"""rename providers.user_id → owner_id; backfill audit_log JSON keys

Aligns Provider with the codebase's standard `owner_id` naming for FKs
to the owning user. After this rename, the auth predicates' default
`owner_attr="owner_id"` matches Provider, so the eight explicit
`owner_attr="user_id"` kwargs in `src/logic/providers/provider_processing.py`
collapse to nothing (handled in the same PR).

Two-part migration:

1. Schema: column rename `providers.user_id` → `providers.owner_id`.
   Done via `batch_alter_table` for SQLite compatibility (rebuilds the
   table; CHECK constraints and the unnamed FK to `users.id` are
   reconstructed). No named indexes existed on the column post-#202
   (the historical `uq_provider_profiles_user_id` was dropped in
   `8f20a93effc9`), so nothing else to rename here.

2. Data: rewrites the top-level `"user_id"` key to `"owner_id"` in
   `audit_log.before` and `audit_log.after` for rows where
   `resource_type = 'provider'` (post-#306). The `ProviderAuditSnapshot`
   schema field also renames in this PR, so any historical row whose
   blob still has `"user_id"` would otherwise fail to validate the next
   time it's loaded against the new schema.

SQLite-only deployment — uses `json_set` / `json_remove` / `json_extract`
from SQLite's json1 extension. The downgrade mirrors both halves.

Revision ID: e24d955563a5
Revises: 478d9e8f19f0
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e24d955563a5"
down_revision: Union[str, None] = "478d9e8f19f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rewrite_audit_log_key(old_key: str, new_key: str) -> None:
    """Rewrite a top-level JSON key on `audit_log.before` and `.after`
    for `resource_type = 'provider'` rows. Idempotent: rows whose blob
    no longer contains `old_key` are left alone by the WHERE clause.
    """
    bind = op.get_bind()
    for column in ("before", "after"):
        bind.execute(sa.text(f"""
                UPDATE audit_log
                   SET {column} = json_set(
                                    json_remove({column}, '$.{old_key}'),
                                    '$.{new_key}',
                                    json_extract({column}, '$.{old_key}')
                                  )
                 WHERE resource_type = 'provider'
                   AND json_extract({column}, '$.{old_key}') IS NOT NULL
                """))


def upgrade() -> None:
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("user_id", new_column_name="owner_id")

    _rewrite_audit_log_key("user_id", "owner_id")


def downgrade() -> None:
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("owner_id", new_column_name="user_id")

    _rewrite_audit_log_key("owner_id", "user_id")
