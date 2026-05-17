"""drop providers.accepts_in_network; flip accepts_out_of_network default to True

`accepts_in_network` carried no independent information: a cross-field
invariant in the wire schema pinned
`accepts_in_network == bool(in_network_carriers)`. Dropping it collapses
the provider's insurance shape to two fields — `in_network_carriers`
(empty = no in-network) plus `accepts_out_of_network` — which captures
the same 4 realities (self-pay, OON-only, in-network, both) without an
invariant.

Same revision also flips the `accepts_out_of_network` server_default
from `0` to `1`. Most practices accept OON; the previous default forced
every caller to opt in. Existing rows are not touched — only the
INSERT default changes.

No backfill needed for the column drop: every existing row already
satisfies `accepts_in_network == (len(in_network_carriers) > 0)`,
enforced by the schema since #449.

Downgrade re-adds `accepts_in_network` nullable, backfills via
`json_array_length(in_network_carriers) > 0`, then tightens to NOT NULL
with a server_default of 0; also flips the OON server_default back to 0.

Revision ID: 9a2b3c4d5e6f
Revises: 8f7e4d2c1a9b
Create Date: 2026-05-17 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a2b3c4d5e6f"
down_revision: Union[str, None] = "8f7e4d2c1a9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_column("accepts_in_network")
        batch_op.alter_column("accepts_out_of_network", server_default=sa.text("1"))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("accepts_out_of_network", server_default=sa.text("0"))
        batch_op.add_column(
            sa.Column(
                "accepts_in_network",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=True,
            )
        )

    op.execute(
        "UPDATE providers SET accepts_in_network = "
        "  CASE WHEN json_array_length(in_network_carriers) > 0 THEN 1 ELSE 0 END"
    )

    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("accepts_in_network", nullable=False)
