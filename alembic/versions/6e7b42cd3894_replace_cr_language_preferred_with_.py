"""replace_cr_language_preferred_with_languages

Revision ID: 6e7b42cd3894
Revises: 2bed07fb1d76
Create Date: 2026-05-11 21:28:47.757667

Sibling to revision `2bed07fb1d76`. `client_referral.language_preferred`
was a yes/no enum signaling "referrer wants a non-English-speaking
provider" without naming which language. Swap for a `languages` JSON
list over a controlled vocabulary (#428).

"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6e7b42cd3894"
down_revision: Union[str, None] = "2bed07fb1d76"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Upgrade schema.

    Same SQLite gotcha as `2bed07fb1d76`: the old column carries a named
    CHECK constraint, so a plain `DROP COLUMN` leaves a dangling
    reference. Use `batch_alter_table` for the table-rewrite path.
    """
    conn = op.get_bind()
    yes_rows = conn.execute(
        sa.text(
            "SELECT post_id FROM client_referral_details "
            "WHERE language_preferred = 'yes'"
        )
    ).fetchall()
    for (post_id,) in yes_rows:
        logger.warning(
            "Row post_id=%s had language_preferred='yes'; defaulted "
            "languages to ['en'] — needs owner update to record the actual "
            "preferred language.",
            post_id,
        )

    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "languages",
                sa.JSON(),
                server_default=sa.text("'[\"en\"]'"),
                nullable=False,
            ),
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_language_preferred",
            type_="check",
        )
        batch_op.drop_column("language_preferred")


def downgrade() -> None:
    """Downgrade schema.

    Lossy: the old yes/no flag is restored as "no" for every row,
    regardless of what `languages` contained.
    """
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "language_preferred",
                sa.TEXT(),
                server_default=sa.text("'no'"),
                nullable=False,
            ),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_language_preferred",
            "language_preferred IN ('no', 'yes')",
        )
        batch_op.drop_column("languages")
