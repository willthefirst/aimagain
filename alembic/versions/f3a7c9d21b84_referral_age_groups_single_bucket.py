"""referral age_groups capped at one bucket

Revision ID: f3a7c9d21b84
Revises: cd0035013698
Create Date: 2026-06-20 00:00:00.000000

A referral describes a single client, so `referral_details.age_groups`
carries *at most one* age bucket. The wire shape stays a JSON list
(`RequiredAgeGroupsField`, now exactly-one) so the read/response/audit
projections and `view.py`'s `age_groups[0]` keep working unchanged; this
migration pins the cardinality in storage with a CHECK.

This is a *cardinality* CHECK — distinct from the "vocabulary on the wire,
no SQL CHECK against array members" convention the other JSON-list columns
follow. Openings/programs keep their multi-valued `age_groups` on the
linked affiliation/program and are untouched.

Backfill: any pre-existing row with more than one bucket is truncated to
its first element before the constraint is added (matches `view.py`, which
already rendered only `age_groups[0]`). Empty lists are left as-is.
Downgrade drops the CHECK only — the truncation is not reversible.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f3a7c9d21b84"
down_revision: Union[str, None] = "cd0035013698"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Truncate any multi-bucket row to its first element so the new CHECK
    # can be added without rejecting existing data.
    op.execute(
        "UPDATE referral_details "
        "SET age_groups = json_array(json_extract(age_groups, '$[0]')) "
        "WHERE json_array_length(age_groups) > 1"
    )
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.create_check_constraint(
            "ck_referral_details_age_groups_single",
            "json_array_length(age_groups) <= 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint("ck_referral_details_age_groups_single", type_="check")
