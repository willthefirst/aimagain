"""rename program_availability → intake

Final rename in the post-kind vocabulary refresh — completes the trio
`referral · opening · intake` (see #627).

Schema layer:

  - ``posts.kind`` value ``program_availability`` → ``intake``
  - ``program_availability_details`` table → ``intake_details``
  - CHECK constraint on ``posts.kind`` tightened to the new vocabulary.

Mirrors the upgrade/downgrade shape of
``e9d8c7b6a5f4_rename_provider_availability_and_client_referral_kinds.py``:
the CHECK must temporarily admit both old and new values so the
``UPDATE`` doesn't violate the constraint mid-flight.

  1. Widen the CHECK to permit both ``program_availability`` and ``intake``.
  2. UPDATE existing ``posts`` rows: ``kind = 'intake'``.
  3. Tighten the CHECK to the final vocabulary
     (``referral``, ``opening``, ``intake``).
  4. Rename the detail table.

Model-class renames (``ProgramAvailabilityDetail`` →
``IntakeDetail``), POST_KINDS key rename, schema/template/test
renames ride in the same PR.

Revision ID: 4a8b2c5d9e1f
Revises: e9d8c7b6a5f4
Create Date: 2026-05-19 14:30:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a8b2c5d9e1f"
down_revision: Union[str, None] = "e9d8c7b6a5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Widen the CHECK to permit both the old and the new value so
    #    the UPDATE below doesn't violate the constraint mid-flight.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'program_availability', 'intake')",
        )

    # 2. Migrate existing data. Idempotent — running twice would no-op.
    op.execute("UPDATE posts SET kind = 'intake' WHERE kind = 'program_availability'")

    # 3. Tighten the CHECK to the final vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'intake')",
        )

    # 4. Rename the detail table. SQLite's batch mode rebuilds the
    #    table internally; Postgres renames in place and preserves FKs
    #    and indexes against the renamed table by id.
    op.rename_table("program_availability_details", "intake_details")


def downgrade() -> None:
    """Downgrade schema.

    Mirror of ``upgrade()`` in reverse: rename the table back, widen
    the CHECK to admit both values, migrate values back, tighten the
    CHECK to the pre-rename vocabulary.
    """
    # 1. Rename the table back.
    op.rename_table("intake_details", "program_availability_details")

    # 2. Widen the CHECK to permit both values during the inverse UPDATE.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'program_availability', 'intake')",
        )

    # 3. Migrate data back.
    op.execute("UPDATE posts SET kind = 'program_availability' WHERE kind = 'intake'")

    # 4. Tighten the CHECK to the pre-rename vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'program_availability')",
        )
