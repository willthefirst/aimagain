"""collapse location_in_person and location_virtual to session_format

Revision ID: 724d4247d7a5
Revises: 89e2e863e214
Create Date: 2026-06-13 18:51:01.521398

`referral_details.location_in_person` and `.location_virtual` were two
independent `{yes, no, please_contact}` axes. In corpus practice they
only ever resolved to four mutually-exclusive states, so we collapse to
a single `session_format` column with vocab `{in_person_only,
virtual_only, either, please_contact}`. Backfill maps the old pair to
the new value before the old columns are dropped.

SQLite needs `batch_alter_table` when the dropped columns are referenced
by named CHECK constraints (see alembic/README.md). The two old CHECKs
(`ck_referral_details_location_in_person`,
`ck_referral_details_location_virtual`) are dropped inside the batch.
The new `ck_referral_details_session_format` is added inside the
same batch so the constraint lands atomically with the column.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "724d4247d7a5"
down_revision: Union[str, None] = "89e2e863e214"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SESSION_FORMAT_BACKFILL = sa.text("""
    UPDATE referral_details
    SET session_format = CASE
        WHEN location_in_person = 'please_contact'
             OR location_virtual = 'please_contact' THEN 'please_contact'
        WHEN location_in_person = 'yes' AND location_virtual = 'yes' THEN 'either'
        WHEN location_in_person = 'yes' AND location_virtual = 'no'  THEN 'in_person_only'
        WHEN location_in_person = 'no'  AND location_virtual = 'yes' THEN 'virtual_only'
        WHEN location_in_person = 'no'  AND location_virtual = 'no'  THEN 'please_contact'
        ELSE 'either'
    END
    """)

# Reverse-direction backfill on downgrade. The mapping isn't fully
# reversible (the old shape encoded more states than the new one uses),
# so we pick the canonical pair per new value: `either` → ('yes','yes'),
# `in_person_only` → ('yes','no'), `virtual_only` → ('no','yes'),
# `please_contact` → ('please_contact','please_contact'). Same shape as
# `_SESSION_FORMAT_TO_AXES` in `src/domain/logic/posts/view.py`.
_LOCATION_AXES_BACKFILL = sa.text("""
    UPDATE referral_details
    SET
        location_in_person = CASE session_format
            WHEN 'in_person_only' THEN 'yes'
            WHEN 'virtual_only'   THEN 'no'
            WHEN 'either'         THEN 'yes'
            WHEN 'please_contact' THEN 'please_contact'
        END,
        location_virtual = CASE session_format
            WHEN 'in_person_only' THEN 'no'
            WHEN 'virtual_only'   THEN 'yes'
            WHEN 'either'         THEN 'yes'
            WHEN 'please_contact' THEN 'please_contact'
        END
    """)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "session_format",
                sa.Text(),
                server_default=sa.text("'either'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_referral_details_session_format",
            (
                "session_format IN ('in_person_only', 'virtual_only',"
                " 'either', 'please_contact')"
            ),
        )

    op.execute(_SESSION_FORMAT_BACKFILL)

    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint(
            "ck_referral_details_location_in_person", type_="check"
        )
        batch_op.drop_constraint("ck_referral_details_location_virtual", type_="check")
        batch_op.drop_column("location_in_person")
        batch_op.drop_column("location_virtual")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "location_in_person",
                sa.Text(),
                server_default=sa.text("'yes'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "location_virtual",
                sa.Text(),
                server_default=sa.text("'no'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_referral_details_location_in_person",
            "location_in_person IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_referral_details_location_virtual",
            "location_virtual IN ('yes', 'no', 'please_contact')",
        )

    op.execute(_LOCATION_AXES_BACKFILL)

    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint("ck_referral_details_session_format", type_="check")
        batch_op.drop_column("session_format")
