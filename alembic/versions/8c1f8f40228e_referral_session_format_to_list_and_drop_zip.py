"""referral session_format to list, drop location_zip

Revision ID: 8c1f8f40228e
Revises: 724d4247d7a5
Create Date: 2026-06-14 16:30:00.000000

Two contract changes on `referral_details`:

* `session_format` was a single TEXT column in the four-value vocabulary
  `{in_person_only, virtual_only, either, please_contact}`. It's now a
  JSON list — any subset of `{in_person, virtual}`. Empty list =
  "unspecified". The form is a multi-checkbox.
* `location_zip` is dropped: referrals model a client's region, not a
  postal address. `ClinicianAffiliation` keeps its ZIP.

Per the workstream owner: no data preservation required — existing rows
are reset to the empty list. Downgrade reverts to the four-value scalar
default `'either'` and re-adds a nullable `location_zip`.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8c1f8f40228e"
down_revision: Union[str, None] = "724d4247d7a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.drop_constraint("ck_referral_details_session_format", type_="check")
        batch_op.drop_column("session_format")
        batch_op.add_column(
            sa.Column(
                "session_format",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.drop_column("location_zip")


def downgrade() -> None:
    with op.batch_alter_table("referral_details") as batch_op:
        batch_op.add_column(
            sa.Column(
                "location_zip",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.drop_column("session_format")
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
