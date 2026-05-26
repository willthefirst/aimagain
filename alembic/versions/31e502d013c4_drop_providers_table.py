"""Drop providers table

Part 2 of removing providers. After b5d2e8f1a3c9 retargeted all FK
columns away from providers, this migration drops the table itself.
The architecture going forward is: orgs, users, clinicians only.

Revision ID: 31e502d013c4
Revises: b5d2e8f1a3c9
Create Date: 2026-05-26
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "31e502d013c4"
down_revision: Union[str, None] = "b5d2e8f1a3c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("providers")


def downgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
