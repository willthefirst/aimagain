"""rename provider_availability → opening, client_referral → referral

Renames two post-kind discriminators (and their detail tables) end-to-end:

  - ``provider_availability`` → ``opening``
    ``provider_availability_details`` → ``opening_details``
  - ``client_referral`` → ``referral``
    ``client_referral_details`` → ``referral_details``

The third kind ``program_availability`` is intentionally NOT touched.

Order matters. The CHECK on ``posts.kind`` must allow both the old and
the new values during the data update (otherwise the UPDATE statements
violate the constraint mid-flight). Sequence:

  1. Widen the CHECK to permit *both* old and new values.
  2. UPDATE existing ``posts`` rows: ``kind`` old → new.
  3. Tighten the CHECK to permit only the new values.
  4. Rename the detail tables.

Step 4 last because the table renames don't affect the kind values —
they're independent operations on different objects. Doing the renames
after the data migration keeps each step's blast radius small.

Schema-only — no business-logic migration needed; the model class
renames + POST_KINDS key renames are application-layer changes that
land in the same PR.

Revision ID: e9d8c7b6a5f4
Revises: 73eb6dcb6908
Create Date: 2026-05-18 19:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9d8c7b6a5f4"
down_revision: Union[str, None] = "73eb6dcb6908"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Widen the CHECK to permit both old and new values so the
    #    forthcoming UPDATEs don't violate the constraint mid-flight.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'referral', "
            "'provider_availability', 'opening', "
            "'program_availability')",
        )

    # 2. Migrate existing data. Idempotent — running twice would no-op
    #    on the second pass since the WHERE clauses would match zero rows.
    op.execute("UPDATE posts SET kind = 'opening' WHERE kind = 'provider_availability'")
    op.execute("UPDATE posts SET kind = 'referral' WHERE kind = 'client_referral'")

    # 3. Tighten the CHECK to permit only the new vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('referral', 'opening', 'program_availability')",
        )

    # 4. Rename the per-kind detail tables. SQLite's batch mode rebuilds
    #    the table internally, picking up the new name on every FK and
    #    index that references it. Postgres handles the rename in place
    #    and preserves FKs / indexes against the renamed table by id.
    op.rename_table("provider_availability_details", "opening_details")
    op.rename_table("client_referral_details", "referral_details")


def downgrade() -> None:
    """Downgrade schema.

    Mirror of ``upgrade()`` in reverse order: rename tables back, widen
    CHECK to admit both, migrate values back, tighten CHECK to the old
    vocabulary.
    """
    # 1. Rename tables back to the old names.
    op.rename_table("opening_details", "provider_availability_details")
    op.rename_table("referral_details", "client_referral_details")

    # 2. Widen the CHECK to permit both old and new values during the
    #    inverse UPDATE.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'referral', "
            "'provider_availability', 'opening', "
            "'program_availability')",
        )

    # 3. Migrate data back.
    op.execute("UPDATE posts SET kind = 'provider_availability' WHERE kind = 'opening'")
    op.execute("UPDATE posts SET kind = 'client_referral' WHERE kind = 'referral'")

    # 4. Tighten the CHECK to the pre-rename vocabulary.
    with op.batch_alter_table("posts") as batch_op:
        batch_op.drop_constraint("ck_posts_kind", type_="check")
        batch_op.create_check_constraint(
            "ck_posts_kind",
            "kind IN ('client_referral', 'provider_availability', "
            "'program_availability')",
        )
