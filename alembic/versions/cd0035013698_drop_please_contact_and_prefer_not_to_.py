"""drop please_contact and prefer_not_to_say vocab

Revision ID: cd0035013698
Revises: adbb4cbd8b99
Create Date: 2026-06-20 16:45:21.806164

Removes three retired vocabulary values across the schema:

  * ``please_contact`` from ``LocationAvailability`` — the
    ``clinician_affiliations.{in_person_sessions,virtual_sessions}``
    columns are the only DB-CHECK-constrained home. Existing
    ``please_contact`` rows backfill to NULL ("unset"), the only honest
    mapping once the explicit "ask me" value is gone, then the CHECK
    rewrites to ``IN ('yes', 'no')``.
  * ``prefer_not_to_say`` from ``Gender`` and ``Pronouns`` — stored only
    in JSON list columns (``genders`` on affiliations/programs,
    ``pronouns`` on referrals); no CHECK, so the token is just stripped
    from any persisted array. (``genders`` is rendered via a direct
    ``GENDER_LABELS[g]`` subscript, so an orphaned token would crash the
    facts block — stripping is load-bearing, not cosmetic.)
  * ``contact_to_discuss`` from ``SessionFormat`` — JSON
    ``referral_details.session_format`` list; stripped like the above.

Downgrade restores the wider CHECK but cannot recover the data that the
upgrade collapsed (please_contact → NULL) or stripped from JSON arrays.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cd0035013698"
down_revision: Union[str, None] = "adbb4cbd8b99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _strip_json_token(table: str, column: str, token: str) -> None:
    """Remove ``token`` from every persisted JSON-array ``column`` value.

    DB-agnostic: reads each row's raw value (a JSON string under SQLite, a
    list under a JSON-native driver), filters the token, and writes back
    only when the array actually changed.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"SELECT rowid AS _rid, {column} AS _val FROM {table}")
    ).fetchall()
    for rid, raw in rows:
        if raw is None:
            continue
        value = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(value, list) or token not in value:
            continue
        cleaned = [v for v in value if v != token]
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :val WHERE rowid = :rid"),
            {"val": json.dumps(cleaned), "rid": rid},
        )


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Collapse the retired session-availability value to NULL before the
    #    new CHECK (which forbids it) is installed.
    op.execute(
        "UPDATE clinician_affiliations SET in_person_sessions = NULL "
        "WHERE in_person_sessions = 'please_contact'"
    )
    op.execute(
        "UPDATE clinician_affiliations SET virtual_sessions = NULL "
        "WHERE virtual_sessions = 'please_contact'"
    )

    # 2. Strip retired tokens from the unconstrained JSON list columns.
    _strip_json_token("clinician_affiliations", "genders", "prefer_not_to_say")
    _strip_json_token("programs", "genders", "prefer_not_to_say")
    _strip_json_token("referral_details", "pronouns", "prefer_not_to_say")
    _strip_json_token("referral_details", "session_format", "contact_to_discuss")

    # 3. Shrink the session-availability CHECK constraints to {yes, no}.
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.drop_constraint(
            "ck_clinician_affiliations_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_clinician_affiliations_virtual_sessions", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_in_person_sessions",
            "in_person_sessions IN ('yes', 'no')",
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_virtual_sessions",
            "virtual_sessions IN ('yes', 'no')",
        )


def downgrade() -> None:
    """Downgrade schema.

    Restores the wider CHECK vocabulary. The data the upgrade collapsed
    (please_contact → NULL) or stripped from JSON arrays is not
    recoverable and is left as-is.
    """
    with op.batch_alter_table("clinician_affiliations") as batch_op:
        batch_op.drop_constraint(
            "ck_clinician_affiliations_in_person_sessions", type_="check"
        )
        batch_op.drop_constraint(
            "ck_clinician_affiliations_virtual_sessions", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_in_person_sessions",
            "in_person_sessions IN ('yes', 'no', 'please_contact')",
        )
        batch_op.create_check_constraint(
            "ck_clinician_affiliations_virtual_sessions",
            "virtual_sessions IN ('yes', 'no', 'please_contact')",
        )
