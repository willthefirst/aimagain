"""move_insurance_to_provider

Revision ID: 48cf70d31112
Revises: 537ba27726f9
Create Date: 2026-05-12 17:30:00.000000

#449: insurance posture moves from `provider_availability_details` to
`providers`, and gets restructured into orthogonal fields:

- Drop from PA: `payment_situation`, `sliding_scale`, `cost`.
- Add to Provider: `accepts_in_network`, `accepts_out_of_network`,
  `in_network_carriers` (JSON list), `sliding_scale`, `cost`.
- Drop `in_and_out_of_network` from the `INSURANCE_OPTIONS` vocab; CR
  rows holding the composite token get backfilled to `out_of_network`.

The composite `payment_situation` token decomposes per Provider:

- `in_network` → in-network only; carriers seed `["other"]` since the
  specific carriers aren't known from the old token.
- `out_of_network` → out-of-network only.
- `in_and_out_of_network` → both; carriers seed `["other"]`.
- `self_pay_only` / `please_contact` → neither; carriers empty.

Each Provider in dev has at most one PA pointing at it; if multiple do,
the first found wins (the others' insurance posture is lost — acceptable
for development data).

Downgrade reverses: re-add the three PA columns nullable, backfill from
Provider, tighten to NOT NULL, then drop the five Provider columns and
restore the wider CR CHECK.

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48cf70d31112"
down_revision: Union[str, None] = "537ba27726f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NARROW_INSURANCE_CK = (
    "insurance IN ('in_network', 'out_of_network', 'self_pay_only', 'please_contact')"
)
_WIDE_INSURANCE_CK = (
    "insurance IN ('in_network', 'out_of_network', 'in_and_out_of_network', "
    "'self_pay_only', 'please_contact')"
)


def upgrade() -> None:
    # 1) Add the five new Provider columns, all NOT NULL with server
    # defaults so the existing seeded Providers stay valid through the
    # backfill.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.add_column(
            sa.Column(
                "accepts_in_network",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        batch_op.add_column(
            sa.Column(
                "accepts_out_of_network",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        batch_op.add_column(
            sa.Column(
                "in_network_carriers",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
        batch_op.add_column(
            sa.Column(
                "sliding_scale",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )
        batch_op.add_column(sa.Column("cost", sa.Text(), nullable=True))

    bind = op.get_bind()

    # 2) Backfill new Provider columns from the linked PA row. Pick the
    # first PA when multiple point at the same Provider — at most one
    # exists in dev today.
    rows = bind.execute(sa.text("""
            SELECT pad.provider_id AS provider_id,
                   pad.payment_situation AS payment_situation,
                   pad.sliding_scale AS sliding_scale,
                   pad.cost AS cost
            FROM provider_availability_details AS pad
            """)).fetchall()

    seen: set = set()
    for row in rows:
        provider_id = row.provider_id
        if provider_id in seen:
            continue
        seen.add(provider_id)

        payment_situation = row.payment_situation
        accepts_in_network = False
        accepts_out_of_network = False
        carriers_json = "[]"
        if payment_situation == "in_network":
            accepts_in_network = True
            carriers_json = '["other"]'
        elif payment_situation == "out_of_network":
            accepts_out_of_network = True
        elif payment_situation == "in_and_out_of_network":
            accepts_in_network = True
            accepts_out_of_network = True
            carriers_json = '["other"]'
        # self_pay_only and please_contact: both False, empty carriers.

        bind.execute(
            sa.text("""
                UPDATE providers
                SET accepts_in_network = :accepts_in_network,
                    accepts_out_of_network = :accepts_out_of_network,
                    in_network_carriers = :in_network_carriers,
                    sliding_scale = :sliding_scale,
                    cost = :cost
                WHERE id = :id
                """),
            {
                "id": provider_id,
                "accepts_in_network": accepts_in_network,
                "accepts_out_of_network": accepts_out_of_network,
                "in_network_carriers": carriers_json,
                "sliding_scale": bool(row.sliding_scale),
                "cost": row.cost,
            },
        )

    # 3) Backfill CR rows: collapse `in_and_out_of_network` to
    # `out_of_network` so the narrower CHECK doesn't reject existing data.
    bind.execute(
        sa.text(
            "UPDATE client_referral_details "
            "SET insurance = 'out_of_network' "
            "WHERE insurance = 'in_and_out_of_network'"
        )
    )

    # 4) Narrow the CR CHECK to the new 4-token vocab.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            _NARROW_INSURANCE_CK,
        )

    # 5) Drop PA's payment_situation CHECK + three columns.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_payment_situation", type_="check"
        )
        batch_op.drop_column("payment_situation")
        batch_op.drop_column("sliding_scale")
        batch_op.drop_column("cost")


def downgrade() -> None:
    # Re-add PA's three columns nullable so the table stays valid through
    # the backfill.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.add_column(sa.Column("payment_situation", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("sliding_scale", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("cost", sa.Text(), nullable=True))

    bind = op.get_bind()

    # Backfill from each PA row's linked Provider. Two-booleans →
    # composite token, lossy on the carrier list (the wider Provider
    # universe collapses to one of four tokens).
    pa_rows = bind.execute(sa.text("""
            SELECT pad.post_id AS post_id,
                   p.accepts_in_network AS accepts_in_network,
                   p.accepts_out_of_network AS accepts_out_of_network,
                   p.sliding_scale AS sliding_scale,
                   p.cost AS cost
            FROM provider_availability_details AS pad
            JOIN providers AS p ON p.id = pad.provider_id
            """)).fetchall()

    for row in pa_rows:
        accepts_in = bool(row.accepts_in_network)
        accepts_out = bool(row.accepts_out_of_network)
        if accepts_in and accepts_out:
            payment_situation = "in_and_out_of_network"
        elif accepts_in:
            payment_situation = "in_network"
        elif accepts_out:
            payment_situation = "out_of_network"
        else:
            payment_situation = "self_pay_only"

        bind.execute(
            sa.text("""
                UPDATE provider_availability_details
                SET payment_situation = :payment_situation,
                    sliding_scale = :sliding_scale,
                    cost = :cost
                WHERE post_id = :post_id
                """),
            {
                "post_id": row.post_id,
                "payment_situation": payment_situation,
                "sliding_scale": bool(row.sliding_scale),
                "cost": row.cost,
            },
        )

    # Tighten PA columns to NOT NULL and re-add the CHECK.
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.alter_column("payment_situation", nullable=False)
        batch_op.alter_column("sliding_scale", nullable=False)
        batch_op.create_check_constraint(
            "ck_provider_availability_details_payment_situation",
            "payment_situation IN ('in_network', 'out_of_network', "
            "'in_and_out_of_network', 'self_pay_only', 'please_contact')",
        )

    # Widen the CR CHECK back.
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            _WIDE_INSURANCE_CK,
        )

    # Drop the five Provider columns.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.drop_column("cost")
        batch_op.drop_column("sliding_scale")
        batch_op.drop_column("in_network_carriers")
        batch_op.drop_column("accepts_out_of_network")
        batch_op.drop_column("accepts_in_network")
