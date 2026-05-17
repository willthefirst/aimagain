"""split client_referral_details.insurance into insurance_carrier and network_preference

The single `insurance` column on `client_referral_details` was doing two
jobs at once — describing *what carrier* the patient has (e.g. Cigna)
and *how strict* the referrer is about in-network match (mandatory vs
preferred). The conflation blocked the referral-search model where
provider matching needs both axes (carrier-aware filtering + ranking by
in-network preference). Splitting:

- `insurance_carrier` — nullable Text, vocab from `INSURANCE_CARRIERS`
  (same tuple used by `Provider.in_network_carriers`). Null = self-pay
  / unknown / no carrier — the natural shape when the referrer says
  "no preference". Existing rows backfill to NULL (the old schema
  never captured the carrier).
- `network_preference` — NOT NULL Text, new 3-state vocab
  (`in_network_required` / `in_network_preferred` / `no_preference`).
  Existing rows backfill from `insurance` via:
    in_network      → in_network_required
    out_of_network  → in_network_preferred
    self_pay_only   → no_preference
    please_contact  → no_preference   (please_contact is dropped from
                                       the live vocab going forward)

Downgrade re-creates the old `insurance` column and backfills from
`network_preference`. The mapping is lossy: `please_contact` rows
can't be reconstructed and collapse into `self_pay_only`. Carriers
recorded on the new column are dropped — the old schema had nowhere
to put them.

Revision ID: 8f7e4d2c1a9b
Revises: 6c184bb07379
Create Date: 2026-05-17 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f7e4d2c1a9b"
down_revision: Union[str, None] = "6c184bb07379"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Vocabulary pinned at migration-author time. Keep in lockstep with the
# tuples in `src/domain/models/enums.py`. The migration is a *snapshot*;
# widening either enum in code requires a follow-up migration that
# drops + re-adds the CHECK constraint.
_NETWORK_PREFERENCES: tuple[str, ...] = (
    "in_network_required",
    "in_network_preferred",
    "no_preference",
)
_INSURANCE_CARRIERS: tuple[str, ...] = (
    "aetna",
    "anthem_bcbs",
    "cigna",
    "kaiser",
    "magellan",
    "medicare",
    "medicaid",
    "optum",
    "tricare",
    "united_healthcare",
    "other",
)


def _check_in_sql(column: str, values: tuple[str, ...]) -> str:
    """Render a `<column> IN (...)` CHECK body — same shape the runtime
    `named_check_in` helper produces, but the migration can't import
    that without coupling to a moving target."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    """Upgrade schema."""
    # 1) Add both new columns. `network_preference` is NOT NULL with a
    # server_default so existing rows stay valid through the backfill;
    # `insurance_carrier` is nullable and starts NULL for every row
    # (the old schema never captured the patient's carrier).
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.add_column(sa.Column("insurance_carrier", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "network_preference",
                sa.Text(),
                server_default=sa.text("'no_preference'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance_carrier",
            _check_in_sql("insurance_carrier", _INSURANCE_CARRIERS),
        )
        batch_op.create_check_constraint(
            "ck_client_referral_details_network_preference",
            _check_in_sql("network_preference", _NETWORK_PREFERENCES),
        )

    # 2) Backfill `network_preference` from the old `insurance` column.
    # `please_contact` collapses into `no_preference` (it was always a
    # "talk to me" escape hatch; the new model surfaces that via the
    # form UX rather than a stored value).
    op.execute(
        "UPDATE client_referral_details SET network_preference = CASE insurance "
        "  WHEN 'in_network' THEN 'in_network_required' "
        "  WHEN 'out_of_network' THEN 'in_network_preferred' "
        "  WHEN 'self_pay_only' THEN 'no_preference' "
        "  WHEN 'please_contact' THEN 'no_preference' "
        "  ELSE 'no_preference' "
        "END"
    )

    # 3) Drop the old `insurance` column + CHECK. CHECK drops first to
    # avoid the SQLite "after drop column: no such column" gotcha
    # (see alembic/README.md).
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.drop_column("insurance")


def downgrade() -> None:
    """Downgrade schema."""
    # 1) Re-add `insurance` nullable so the table stays valid through
    # the backfill, then re-create its CHECK.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.add_column(sa.Column("insurance", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            "insurance IN ('in_network', 'out_of_network', 'self_pay_only', "
            "'please_contact')",
        )

    # 2) Backfill `insurance` from `network_preference`. The mapping is
    # lossy: original `please_contact` rows are indistinguishable from
    # `self_pay_only` rows and collapse together.
    op.execute(
        "UPDATE client_referral_details SET insurance = CASE network_preference "
        "  WHEN 'in_network_required' THEN 'in_network' "
        "  WHEN 'in_network_preferred' THEN 'out_of_network' "
        "  WHEN 'no_preference' THEN 'self_pay_only' "
        "  ELSE 'self_pay_only' "
        "END"
    )

    # 3) Tighten `insurance` to NOT NULL now that every row has a value.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.alter_column("insurance", nullable=False)

    # 4) Drop the two new columns + their CHECKs. CHECK drops first per
    # the SQLite gotcha.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint(
            "ck_client_referral_details_network_preference", type_="check"
        )
        batch_op.drop_constraint(
            "ck_client_referral_details_insurance_carrier", type_="check"
        )
        batch_op.drop_column("network_preference")
        batch_op.drop_column("insurance_carrier")
