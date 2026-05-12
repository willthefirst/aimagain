"""replace_non_english_services_with_languages

Revision ID: 2bed07fb1d76
Revises: a50977e5627b
Create Date: 2026-05-11 21:12:26.375418

`provider_availability.non_english_services` was a yes/no enum that
indicated *some* non-English language was spoken but not *which*. This
revision swaps it for a `languages` JSON list over a controlled
vocabulary (#425). Backfill is lossy by design — every existing row gets
`["en"]`, with a warning when the prior value was "yes" (those rows need
owner attention to record the actual non-English language).

"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2bed07fb1d76"
down_revision: Union[str, None] = "a50977e5627b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Upgrade schema.

    The old column carried a named CHECK constraint
    (`ck_provider_availability_details_non_english_services`), so a plain
    `DROP COLUMN` would leave a dangling reference under SQLite. Use
    `batch_alter_table` to drop constraint + column in one rewrite.
    """
    # Backfill warning first — needs the old column still present.
    conn = op.get_bind()
    yes_rows = conn.execute(
        sa.text(
            "SELECT post_id FROM provider_availability_details "
            "WHERE non_english_services = 'yes'"
        )
    ).fetchall()
    for (post_id,) in yes_rows:
        logger.warning(
            "Row post_id=%s had non_english_services='yes'; defaulted "
            "languages to ['en'] — needs owner update to record the actual "
            "non-English language.",
            post_id,
        )

    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "languages",
                sa.JSON(),
                server_default=sa.text("'[\"en\"]'"),
                nullable=False,
            ),
        )
        batch_op.drop_constraint(
            "ck_provider_availability_details_non_english_services",
            type_="check",
        )
        batch_op.drop_column("non_english_services")


def downgrade() -> None:
    """Downgrade schema.

    Lossy: the old yes/no flag is restored as "no" for every row,
    regardless of what `languages` contained.
    """
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "non_english_services",
                sa.TEXT(),
                server_default=sa.text("'no'"),
                nullable=False,
            ),
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_non_english_services",
            "non_english_services IN ('no', 'yes')",
        )
        batch_op.drop_column("languages")
