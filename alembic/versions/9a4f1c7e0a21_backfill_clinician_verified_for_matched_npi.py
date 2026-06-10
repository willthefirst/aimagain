"""backfill clinician_verified for matched NPI

Data backfill for the Claim-A rule change: previously
``recompute_clinician_claim`` required matched NPI AND ≥1 active
licensure. Solo clinicians with a matched NPI but no licensure stayed
``clinician_verified=False``. The rule now requires only matched NPI,
so flip the denorm cache for those rows and stamp the timestamps the
recompute helper would have set.

Schema-only migrations are the norm here (see alembic/README.md), but
this is a denorm-cache realignment that has to ship with the code
change — otherwise existing matched-NPI clinicians stay unverified
until the next worker pass touches them.

Revision ID: 9a4f1c7e0a21
Revises: 43c694311395
Create Date: 2026-06-09

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a4f1c7e0a21"
down_revision: Union[str, None] = "43c694311395"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set ``clinician_verified=True`` (+ timestamps) for every
    clinician whose ``npi_match_status`` is ``matched`` but whose denorm
    cache is still False. Idempotent: rows already True are untouched.
    """
    op.execute(sa.text("""
            UPDATE clinicians
            SET clinician_verified = 1,
                verified_at = COALESCE(verified_at, CURRENT_TIMESTAMP),
                ever_verified_at = COALESCE(ever_verified_at, CURRENT_TIMESTAMP)
            WHERE npi_match_status = 'matched'
              AND clinician_verified = 0
            """))


def downgrade() -> None:
    """Data-only migration: leave the cache as-is on downgrade. Reverting
    the cache to the old rule would require re-joining licensures and
    re-running the predicate; in practice the code rollback alone is
    enough since the next recompute under the old rule will correct
    any row whose state actually changed.
    """
