"""payment paths refactor for referral_details

Replaces the asymmetric ``network_preference`` (scalar enum) +
``insurance_carrier`` (nullable scalar) shape with three independent
payment-path booleans plus an ``insurance_carriers`` JSON list
(#1358 PR-e).

The corpus analysis in #1355 surfaced the original model's semantic
collapse: ``no_preference + null carrier`` overloaded to mean both
"I don't care" and "private pay", and the three payment paths
("Anthem PPO; private pay okay") are not mutually exclusive. This
migration matches the data shape to the real-world referral pattern
and fixes the request-side-scalar vs provider-side-list asymmetry
(``ClinicianAffiliation.in_network_carriers`` is already a JSON list).

Schema change:

  ADD     ``accepts_in_network``                  BOOLEAN NOT NULL DEFAULT 0
  ADD     ``accepts_out_of_network_superbill``    BOOLEAN NOT NULL DEFAULT 0
  ADD     ``accepts_private_pay``                 BOOLEAN NOT NULL DEFAULT 0
  ADD     ``insurance_carriers``                  JSON    NOT NULL DEFAULT '[]'
  DROP    ``network_preference``                  (CHECK-constrained)
  DROP    ``insurance_carrier``                   (CHECK-constrained)

The dropped columns carry named CHECK constraints
(``ck_referral_details_network_preference`` /
``ck_referral_details_insurance_carrier``); SQLite needs
``batch_alter_table`` to rewrite the table (see ``alembic/README.md``).

Backfill rules (applied after the new columns land but before the old
ones are dropped, so we can read them):

  * ``network_preference == 'in_network_required'``
      → ``accepts_in_network = true``
  * ``network_preference == 'in_network_preferred'``
      → ``accepts_in_network = true``,
        ``accepts_out_of_network_superbill = true``,
        ``accepts_private_pay = true``
  * ``network_preference == 'no_preference'`` AND carrier IS NOT NULL
      → ``accepts_in_network = true``,
        ``accepts_private_pay = true``
        (the corpus consistently treats no_preference+carrier as
        "in-network ok, private pay ok")
  * ``network_preference == 'no_preference'`` AND carrier IS NULL
      → ``accepts_private_pay = true``

  * ``insurance_carrier`` (scalar, non-null)
      → ``insurance_carriers = [insurance_carrier]``
  * ``insurance_carrier`` IS NULL
      → ``insurance_carriers = []``

Downgrade is destructive — the three booleans cannot reconstruct the
original 3-state enum lossless (e.g. all-true and "in-network preferred"
both map to the same upgrade output). The downgrade picks a best-effort
inverse: if ``accepts_in_network`` and any other path is true →
``in_network_preferred``; if only ``accepts_in_network`` →
``in_network_required``; else → ``no_preference``. The carrier scalar
takes the first element of ``insurance_carriers`` or NULL.

Revision ID: bf122208871b
Revises: ee1a1aca3db2
Create Date: 2026-06-10 21:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bf122208871b"
down_revision: Union[str, None] = "ee1a1aca3db2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the new payment-path columns, backfill from the legacy
    ``network_preference`` / ``insurance_carrier`` pair, then drop the
    legacy columns (and their named CHECK constraints).
    """
    # 1. Add the four new columns. NOT NULL with server-side defaults so
    #    existing rows pick up `false` / `[]` at column-add time; the
    #    backfill below overrides for rows with meaningful legacy data.
    op.add_column(
        "referral_details",
        sa.Column(
            "accepts_in_network",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "referral_details",
        sa.Column(
            "accepts_out_of_network_superbill",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "referral_details",
        sa.Column(
            "accepts_private_pay",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "referral_details",
        sa.Column(
            "insurance_carriers",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )

    # 2. Backfill existing rows from `network_preference` /
    #    `insurance_carrier`. SQLite-portable UPDATE statements; each
    #    handles one network_preference value at a time so the boolean
    #    set is unambiguous.
    op.execute(
        "UPDATE referral_details "
        "SET accepts_in_network = 1 "
        "WHERE network_preference = 'in_network_required'"
    )
    op.execute(
        "UPDATE referral_details "
        "SET accepts_in_network = 1, "
        "    accepts_out_of_network_superbill = 1, "
        "    accepts_private_pay = 1 "
        "WHERE network_preference = 'in_network_preferred'"
    )
    op.execute(
        "UPDATE referral_details "
        "SET accepts_in_network = 1, accepts_private_pay = 1 "
        "WHERE network_preference = 'no_preference' "
        "  AND insurance_carrier IS NOT NULL"
    )
    op.execute(
        "UPDATE referral_details "
        "SET accepts_private_pay = 1 "
        "WHERE network_preference = 'no_preference' "
        "  AND insurance_carrier IS NULL"
    )

    # `insurance_carriers` backfill — wrap the scalar in a single-element
    # JSON array, or leave at the `'[]'` default for NULL carriers.
    # `json_array(col)` works on SQLite and Postgres alike.
    op.execute(
        "UPDATE referral_details "
        "SET insurance_carriers = json_array(insurance_carrier) "
        "WHERE insurance_carrier IS NOT NULL"
    )

    # 3. Drop the legacy columns + their named CHECK constraints. SQLite
    #    needs `batch_alter_table` to rewrite the table.
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint(
            "ck_referral_details_network_preference", type_="check"
        )
        batch_op.drop_constraint("ck_referral_details_insurance_carrier", type_="check")
        batch_op.drop_column("network_preference")
        batch_op.drop_column("insurance_carrier")


def downgrade() -> None:
    """Restore the legacy ``network_preference`` enum +
    ``insurance_carrier`` scalar pair from the three booleans + JSON
    list. The reverse mapping is intentionally lossy — see the module
    docstring; this is a best-effort inverse, not a round-trip.
    """
    # 1. Add the legacy columns back (without CHECK constraints — those
    #    re-attach inside the batch_alter_table below so they reference
    #    columns that already exist).
    op.add_column(
        "referral_details",
        sa.Column(
            "network_preference",
            sa.Text(),
            server_default=sa.text("'no_preference'"),
            nullable=False,
        ),
    )
    op.add_column(
        "referral_details",
        sa.Column("insurance_carrier", sa.Text(), nullable=True),
    )

    # 2. Backfill the legacy columns from the booleans + carriers list.
    #    Priority order recovers the pre-upgrade posture as best we can:
    #    - all-true (or accepts_in_network with at least one other) →
    #      'in_network_preferred'
    #    - accepts_in_network only → 'in_network_required'
    #    - accepts_private_pay only → 'no_preference'
    #    - else → 'no_preference' (default; matches the pre-existing
    #      semantic for fully-empty referrals).
    op.execute(
        "UPDATE referral_details "
        "SET network_preference = 'in_network_preferred' "
        "WHERE accepts_in_network = 1 "
        "  AND (accepts_out_of_network_superbill = 1 OR accepts_private_pay = 1)"
    )
    op.execute(
        "UPDATE referral_details "
        "SET network_preference = 'in_network_required' "
        "WHERE accepts_in_network = 1 "
        "  AND accepts_out_of_network_superbill = 0 "
        "  AND accepts_private_pay = 0"
    )
    op.execute(
        "UPDATE referral_details "
        "SET network_preference = 'no_preference' "
        "WHERE accepts_in_network = 0"
    )

    # `insurance_carrier` recovers the first element of the JSON list,
    # or NULL if the list is empty.
    op.execute(
        "UPDATE referral_details "
        "SET insurance_carrier = json_extract(insurance_carriers, '$[0]') "
        "WHERE json_array_length(insurance_carriers) > 0"
    )

    # 3. Restore the named CHECK constraints and drop the new columns.
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.create_check_constraint(
            "ck_referral_details_network_preference",
            "network_preference IN ('in_network_required', "
            "'in_network_preferred', 'no_preference')",
        )
        batch_op.create_check_constraint(
            "ck_referral_details_insurance_carrier",
            "insurance_carrier IN ('aetna', 'anthem_bcbs', 'cigna', "
            "'kaiser', 'magellan', 'medicare', 'medicaid', 'optum', "
            "'tricare', 'united_healthcare', 'other')",
        )
        batch_op.drop_column("insurance_carriers")
        batch_op.drop_column("accepts_private_pay")
        batch_op.drop_column("accepts_out_of_network_superbill")
        batch_op.drop_column("accepts_in_network")
