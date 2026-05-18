"""add programs table

PR 4 of the Org/Program roadmap (#537). Introduces ``programs`` as a
first-class entity owned by an :class:`Organization`. No Provider-side
changes — a Program is a treatment offering, distinct from the Provider
who delivers care.

Columns:

* ``org_id`` — FK to ``organizations.id`` (RESTRICT). The owning Org.
* ``owner_id`` — FK to ``users.id`` (CASCADE). The User who created /
  edits the Program. Matches Provider's ownership shape (#537 design
  question 1).
* ``name`` / ``description`` — display strings.
* ``state_preference`` — CHECK-bounded to ``US_STATES``, nullable.
  Explicit column on Program; not derived from the parent Org (#537
  design question 3).
* ``start_date`` / ``end_date`` — optional program window.
* ``accepting_referrals`` — default ``True`` (most programs intake by
  default).

Schema-only per the repo convention in ``alembic/README.md``. No data
migration needed (the table is new and empty).

Revision ID: 2cc8e54d7a19
Revises: d3f8e1c7b9a2
Create Date: 2026-05-17 21:29:57.049505

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2cc8e54d7a19"
down_revision: Union[str, None] = "779078fd2e23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("state_preference", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "accepting_referrals",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "state_preference IN ('AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', "
            "'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', "
            "'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', "
            "'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', "
            "'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY')",
            name="ck_programs_state_preference",
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    Defensive: reject if any ``programs`` rows exist. The table is new
    in this revision; a populated table on downgrade would silently
    lose data (mirrors the pattern from
    ``e7b3c2a8f1d4_add_client_referral_kind.py``).
    """
    bind = op.get_bind()
    leftover = bind.execute(sa.text("SELECT COUNT(*) FROM programs")).scalar()
    if leftover:
        raise RuntimeError(
            f"cannot downgrade: {leftover} program(s) exist; "
            "delete them before downgrading"
        )
    op.drop_table("programs")
