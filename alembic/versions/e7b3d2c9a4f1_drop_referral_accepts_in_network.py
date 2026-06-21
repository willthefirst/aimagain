"""drop referral_details.accepts_in_network

The in-network boolean was redundant: a non-empty `insurance_carriers`
list already states which carriers to bill, so "yes, in-network" added
nothing. In-network status is now derived from carrier presence (the same
way the provider side reads `in_network_carriers`). Openings/intakes are
unaffected — they never had this column.

Revision ID: e7b3d2c9a4f1
Revises: c2f8a1d6e3b9
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b3d2c9a4f1"
down_revision: Union[str, None] = "c2f8a1d6e3b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("referral_details", "accepts_in_network")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "referral_details",
        sa.Column(
            "accepts_in_network",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
