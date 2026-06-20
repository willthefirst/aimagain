"""Rename referral in_network_carrier_notes to insurance_carriers_other_text

Pure column rename on ``referral_details`` — no data is dropped. Unifies the
"Other / please specify" free-text columns under one naming convention:
``services_other_text`` for ``services`` and now
``insurance_carriers_other_text`` for ``insurance_carriers``. Semantics and
validation are unchanged; this is a prep PR. Autogenerate would emit
drop_column + add_column (which loses data), so the bodies below are hand-
written as a batch-mode ``alter_column`` rename (batch mode is required
because the dev DB is SQLite).

Revision ID: 8c4abf2d53fc
Revises: 77849e4d312e
Create Date: 2026-06-20 11:14:22.316829

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c4abf2d53fc"
down_revision: Union[str, None] = "77849e4d312e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.alter_column(
            "in_network_carrier_notes",
            new_column_name="insurance_carriers_other_text",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.alter_column(
            "insurance_carriers_other_text",
            new_column_name="in_network_carrier_notes",
        )
