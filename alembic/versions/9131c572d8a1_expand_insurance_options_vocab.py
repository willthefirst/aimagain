"""expand_insurance_options_vocab

Revision ID: 9131c572d8a1
Revises: bf8725bca464
Create Date: 2026-05-12 06:52:30.895867

#438: widen the `INSURANCE_OPTIONS` controlled vocabulary from
3 tokens (`in_network`, `out_of_network`, `in_and_out_of_network`) to
5 (`+self_pay_only`, `+please_contact`). The CHECK constraint on each
table referencing this vocab gets dropped and re-added.

Two tables share the vocab: `provider_availability_details.payment_situation`
and `client_referral_details.insurance`. Both CHECKs widen together so
the dictionary remains in lockstep.

Existing rows are unaffected — every previously-valid token remains
valid. Downgrade narrows the CHECK back; if any row uses one of the
two new tokens, the downgrade fails and the operator must backfill
before retrying.

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9131c572d8a1"
down_revision: Union[str, None] = "bf8725bca464"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIDE_CK = (
    "{column} IN ('in_network', 'out_of_network', 'in_and_out_of_network', "
    "'self_pay_only', 'please_contact')"
)
_NARROW_CK = "{column} IN ('in_network', 'out_of_network', 'in_and_out_of_network')"


def upgrade() -> None:
    """Widen both CHECKs to admit the two new tokens."""
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_payment_situation", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_payment_situation",
            _WIDE_CK.format(column="payment_situation"),
        )
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            _WIDE_CK.format(column="insurance"),
        )


def downgrade() -> None:
    """Narrow both CHECKs back. Fails if any row uses the new tokens."""
    with op.batch_alter_table("client_referral_details") as batch_op:
        batch_op.drop_constraint("ck_client_referral_details_insurance", type_="check")
        batch_op.create_check_constraint(
            "ck_client_referral_details_insurance",
            _NARROW_CK.format(column="insurance"),
        )
    with op.batch_alter_table("provider_availability_details") as batch_op:
        batch_op.drop_constraint(
            "ck_provider_availability_details_payment_situation", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_provider_availability_details_payment_situation",
            _NARROW_CK.format(column="payment_situation"),
        )
