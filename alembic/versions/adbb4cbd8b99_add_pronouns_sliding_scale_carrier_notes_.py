"""Add pronouns, services_other_text, sliding_scale, in_network_carrier_notes to referral_details

PR-B additive half of the referral-form restructure. The subtractive half
(dropping the seven matching-dimension / demographic columns plus
`desired_times` from opening/intake details) lands first in revision
`606967b5ec1f`; this revision only adds the new columns, so the two PRs
form a clean linear stack.

Revision ID: adbb4cbd8b99
Revises: 606967b5ec1f
Create Date: 2026-06-19 22:25:20.657019

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "adbb4cbd8b99"
down_revision: Union[str, None] = "606967b5ec1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "pronouns",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("services_other_text", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "sliding_scale",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("in_network_carrier_notes", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.drop_column("in_network_carrier_notes")
        batch_op.drop_column("sliding_scale")
        batch_op.drop_column("services_other_text")
        batch_op.drop_column("pronouns")
