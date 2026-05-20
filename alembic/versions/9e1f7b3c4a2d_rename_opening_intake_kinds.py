"""rename opening → clinician_opening, intake → program_intake

Disambiguates the leaf-kind names from the umbrella term "openings":
"opening" the leaf-kind value and "openings" the URL collection are
distinct strings now, eliminating the singular/plural smudge.

Schema layer:

  - ``posts.kind`` value ``opening``  → ``clinician_opening``
  - ``posts.kind`` value ``intake``   → ``program_intake``
  - CHECK constraint on ``posts.kind`` updated to the new vocabulary
    (``referral``, ``clinician_opening``, ``program_intake``).

Mirrors the upgrade/downgrade shape of
``4a8b2c5d9e1f_rename_program_availability_to_intake.py``: the CHECK
must temporarily admit both old and new values so the ``UPDATE`` doesn't
violate the constraint mid-flight.

  1. Widen the CHECK to permit both old and new vocabulary.
  2. UPDATE existing ``posts`` rows.
  3. Tighten the CHECK to the final vocabulary.

Detail tables (``opening_details``, ``intake_details``) keep their
existing names — renaming SQL tables would be migration noise with no
payoff. Only the discriminator string and the Python identifiers shift.

Audit-log historical rows reference the old kind strings in their JSON
``before``/``after`` snapshots. They are intentionally left untouched
— audit history is a record of what happened then, not a projection of
the current name. New audit writes use the new names.

Revision ID: 9e1f7b3c4a2d
Revises: 7c3c296c9429
Create Date: 2026-05-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e1f7b3c4a2d"
down_revision: Union[str, None] = "7c3c296c9429"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Widen the CHECK to permit both the old and the new values so
    #    the UPDATEs below don't violate the constraint mid-flight.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'intake', "
            "'clinician_opening', 'program_intake')",
        )

    # 2. Migrate existing data. Idempotent — running twice would no-op.
    op.execute("UPDATE posts SET kind = 'clinician_opening' WHERE kind = 'opening'")
    op.execute("UPDATE posts SET kind = 'program_intake' WHERE kind = 'intake'")

    # 3. Tighten the CHECK to the final vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'clinician_opening', 'program_intake')",
        )


def downgrade() -> None:
    """Downgrade schema.

    Mirror of ``upgrade()`` in reverse: widen the CHECK to admit both
    values, migrate values back, tighten the CHECK to the pre-rename
    vocabulary.
    """
    # 1. Widen the CHECK to permit both vocabularies during the inverse
    #    UPDATE.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'intake', "
            "'clinician_opening', 'program_intake')",
        )

    # 2. Migrate data back.
    op.execute("UPDATE posts SET kind = 'opening' WHERE kind = 'clinician_opening'")
    op.execute("UPDATE posts SET kind = 'intake' WHERE kind = 'program_intake'")

    # 3. Tighten the CHECK to the pre-rename vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'intake')",
        )
