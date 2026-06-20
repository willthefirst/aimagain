"""drop seven matching-dimension and demographic fields from referral_details

Drops the columns removed in the referral-form-restructure model change:
``desired_times``, ``gender`` (and its CHECK constraint),
``modalities``, ``affirming_identities``, ``acceptable_license_types``,
``clinical_niches``, and ``accepts_out_of_network_superbill``.

``gender`` carries a named CHECK constraint, which SQLite cannot drop via
a bare ``ALTER TABLE ... DROP COLUMN`` (it re-validates the surviving
schema objects and errors on the now-dangling reference). Everything is
therefore folded into a single ``batch_alter_table`` so SQLite recreates
the table once, without the constraint and the seven columns together.

Revision ID: 606967b5ec1f
Revises: 8c1f8f40228e
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "606967b5ec1f"
down_revision: Union[str, None] = "8c1f8f40228e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GENDER_CHECK = (
    "gender IN ('female', 'male', 'non_binary', 'trans_female', "
    "'trans_male', 'gender_diverse', 'prefer_not_to_say')"
)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.drop_constraint("ck_referral_details_gender", type_="check")
        batch_op.drop_column("desired_times")
        batch_op.drop_column("gender")
        batch_op.drop_column("modalities")
        batch_op.drop_column("affirming_identities")
        batch_op.drop_column("acceptable_license_types")
        batch_op.drop_column("clinical_niches")
        batch_op.drop_column("accepts_out_of_network_superbill")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "desired_times",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "gender",
                sa.Text(),
                server_default=sa.text("'prefer_not_to_say'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "modalities",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "affirming_identities",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "acceptable_license_types",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "clinical_niches",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "accepts_out_of_network_superbill",
                sa.Boolean(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint("ck_referral_details_gender", _GENDER_CHECK)
