"""add gender column to client_referral_details and genders to provider_availability_details

Adds the `gender` enum column to `client_referral_details` (single value per
client referral, vocabulary from `GENDERS` in `src/domain/models/enums.py`)
and the `genders` JSON array to `provider_availability_details` (multi-value
list of GENDERS tokens for "which genders this practice serves").

`gender` is NOT NULL with a server_default of `'prefer_not_to_say'` so
existing rows backfill to the privacy-respecting opt-out. The CHECK
constraint pins the vocabulary to `GENDERS` at the SQL layer (Pydantic
also enforces it on the wire). On SQLite the column + CHECK go in via
`batch_alter_table`; the downgrade drops the constraint first to avoid
the "after drop column: no such column" error documented in
`alembic/README.md`.

`genders` is a JSON array; the vocabulary is enforced by Pydantic only
(SQL CHECK against JSON-array members is awkward in SQLite — same
rationale as `services` / `settings` / `age_groups`). Existing rows
backfill to `[]` (empty = "no restriction stated" / serves any).

Revision ID: 6c184bb07379
Revises: c8e1f04a7b32
Create Date: 2026-05-17 12:10:41.451616

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c184bb07379"
down_revision: Union[str, None] = "c8e1f04a7b32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Vocabulary pinned at migration-author time. Keep in lockstep with the
# `GENDERS` tuple in `src/domain/models/enums.py`. The migration is a
# *snapshot*; widening the enum in code requires a follow-up migration
# that drops + re-adds the CHECK constraint.
_GENDERS: tuple[str, ...] = (
    "female",
    "male",
    "non_binary",
    "trans_female",
    "trans_male",
    "gender_diverse",
    "prefer_not_to_say",
)


def _check_in_sql(column: str, values: tuple[str, ...]) -> str:
    """Render a `<column> IN (...)` CHECK body — same shape the runtime
    `named_check_in` helper produces, but the migration can't import
    that without coupling to a moving target."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "gender",
                sa.Text(),
                server_default=sa.text("'prefer_not_to_say'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_gender",
            _check_in_sql("gender", _GENDERS),
        )

    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "genders",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_column("genders")

    # The CHECK constraint must drop before the column on SQLite — see
    # alembic/README.md for the "after drop column" gotcha.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_gender", type_="check")
        batch_op.drop_column("gender")
