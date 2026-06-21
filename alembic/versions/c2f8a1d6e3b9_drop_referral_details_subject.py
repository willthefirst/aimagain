"""drop referral_details.subject

Referrals never exposed `subject` as a form field — the title is always
derived from demographics + services (`post_feed_headline`). The column
was vestigial (only legacy/seed rows ever set it) yet still took
precedence over the derived title, so it's removed entirely. Openings and
intakes keep their own `subject` columns (those kinds do let the poster
set a custom title).

Revision ID: c2f8a1d6e3b9
Revises: f6eec0810036
Create Date: 2026-06-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2f8a1d6e3b9"
down_revision: Union[str, None] = "f6eec0810036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("referral_details", "subject")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "referral_details",
        sa.Column("subject", sa.Text(), nullable=True),
    )
