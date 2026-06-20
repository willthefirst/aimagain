"""Referral: nullable location_city + languages/pronouns other_text columns

Behavioral half of the referral conditional-required work:

  * ``location_city`` becomes nullable — a referral only needs a city for
    in-person sessions; the conditional requirement (in-person → city) is
    enforced on the wire by ``REFERRAL_CONDITIONAL_RULES``
    (``src/domain/logic/posts/conditional_fields.py``), not by NOT NULL.
  * ``languages_other_text`` / ``pronouns_other_text`` are added (nullable)
    to pair with the new ``other`` token in the ``Language`` / ``Pronouns``
    vocabularies — the uniform "Other → please specify" shape that
    ``services_other_text`` / ``insurance_carriers_other_text`` already follow.

Wrapped in ``batch_alter_table`` because the dev DB is SQLite, which can't
ALTER a column's NOT NULL in place — batch mode rebuilds the table.

Revision ID: f6eec0810036
Revises: 8c4abf2d53fc
Create Date: 2026-06-20 11:31:32.020855

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6eec0810036"
down_revision: Union[str, None] = "8c4abf2d53fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.add_column(sa.Column("languages_other_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("pronouns_other_text", sa.Text(), nullable=True))
        batch_op.alter_column("location_city", existing_type=sa.TEXT(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("referral_details", schema=None) as batch_op:
        batch_op.alter_column("location_city", existing_type=sa.TEXT(), nullable=False)
        batch_op.drop_column("pronouns_other_text")
        batch_op.drop_column("languages_other_text")
