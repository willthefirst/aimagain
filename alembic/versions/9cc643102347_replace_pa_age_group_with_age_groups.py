"""replace_pa_age_group_with_age_groups

Revision ID: 9cc643102347
Revises: 6e7b42cd3894
Create Date: 2026-05-11 21:39:17.603031

Provider availability's `age_group` was single-valued — every real-world
post in the seed set spans multiple buckets (#430). Swap for an
`age_groups` JSON list, backfilling each row's prior scalar as a
single-element list. Same `batch_alter_table` SQLite-CHECK trap as
revisions `2bed07fb1d76` and `6e7b42cd3894`; see `alembic/README.md`.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9cc643102347"
down_revision: Union[str, None] = "6e7b42cd3894"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Order matters: add `age_groups` first (with `[]` server_default so
    NOT NULL holds), backfill from `age_group` while the old column
    still exists, then `batch_alter_table` to drop the old column +
    its named CHECK in one rewrite.
    """
    op.add_column(
        "provider_availability_details",
        sa.Column(
            "age_groups",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )

    # SQLite's json_array(x) wraps a single value into a JSON array.
    # Postgres has the same function under the same name — no dialect
    # branching needed.
    op.execute(
        sa.text(
            "UPDATE provider_availability_details "
            "SET age_groups = json_array(age_group)"
        )
    )

    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_age_group",
            type_="check",
        )
        batch_op.drop_column("age_group")


def downgrade() -> None:
    """Downgrade schema.

    Lossy: restore the scalar column from the first element of the list;
    everything beyond `age_groups[0]` is discarded.
    """
    op.add_column(
        "provider_availability_details",
        sa.Column(
            "age_group",
            sa.TEXT(),
            server_default=sa.text("'adults_25_64'"),
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            "UPDATE provider_availability_details "
            "SET age_group = json_extract(age_groups, '$[0]') "
            "WHERE json_array_length(age_groups) > 0"
        )
    )
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.create_check_constraint(
            "ck_provider_availability_details_age_group",
            "age_group IN ('children_0_5', 'children_6_10', 'preteens_11_13', "
            "'adolescents_14_18', 'young_adults_19_24', 'adults_25_64', "
            "'older_adults_65_plus')",
        )
        batch_op.drop_column("age_groups")
