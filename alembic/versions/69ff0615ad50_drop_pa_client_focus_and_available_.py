"""drop_pa_client_focus_and_available_providers

Revision ID: 69ff0615ad50
Revises: 6dfcb644a327
Create Date: 2026-05-12 07:32:13.844200

#444: drop two now-redundant PA columns. `client_focus`'s role is fully
covered by `description` (#422) post-content-merge. `available_providers`
doesn't fit program-style posts and duplicates `practice_name` for solo
practices.

Downgrade restores both as `NOT NULL` with empty-string `server_default`
— lossy on any row inserted post-drop (the previous values are gone),
but structurally reversible.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "69ff0615ad50"
down_revision: Union[str, None] = "6dfcb644a327"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop both columns inside batch_alter_table — SQLite rewrites the
    table once for the pair instead of twice."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_column("client_focus")
        batch_op.drop_column("available_providers")


def downgrade() -> None:
    """Restore both columns as NOT NULL with empty-string defaults.
    Lossy — prior values are gone."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "available_providers",
                sa.TEXT(),
                server_default=sa.text("('')"),
                nullable=False,
            ),
        )
        batch_op.add_column(
            sa.Column(
                "client_focus",
                sa.TEXT(),
                server_default=sa.text("('')"),
                nullable=False,
            ),
        )
