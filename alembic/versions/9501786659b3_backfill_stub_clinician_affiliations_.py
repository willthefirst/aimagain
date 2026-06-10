"""backfill stub clinician_affiliations for unaffiliated clinicians

Data-only migration: restores the "every clinician has ≥1
``ClinicianAffiliation``" invariant for rows created during the gap
between #1296 (which made affiliation-on-create optional) and the
auto-create hook that lands alongside this revision. For every
``Clinician`` with zero affiliations, insert a stub
``ClinicianAffiliation`` with ``org_id`` NULL and all per-affiliation
posture columns at their defaults (in_person_sessions / virtual_sessions
NULL — that is, "not asked yet"; in_network_carriers ``[]``;
accepts_out_of_network True; sliding_scale False; location triple NULL).

Cross-DB UUID generation: SQLite has no native uuid, Postgres has
``gen_random_uuid()``; rather than branch on dialect, generate ids in
Python and bind them. The connection comes from ``op.get_bind()``.

Schema-only is the norm here (see ``alembic/README.md``); this is the
sibling data backfill the schema migration ``82b7dce71362`` requires,
following the same pattern as ``9a4f1c7e0a21`` (claim-A denorm cache
backfill).

Revision ID: 9501786659b3
Revises: 82b7dce71362
Create Date: 2026-06-10 10:01:08.907400

"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9501786659b3"
down_revision: Union[str, None] = "82b7dce71362"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """For every Clinician with zero affiliations, insert a stub
    ``ClinicianAffiliation`` with ``org_id`` NULL.
    """
    bind = op.get_bind()
    unaffiliated = bind.execute(sa.text("""
            SELECT c.id
              FROM clinicians c
         LEFT JOIN clinician_affiliations a
                ON a.clinician_id = c.id
             WHERE a.id IS NULL
            """)).all()

    if not unaffiliated:
        return

    bind.execute(
        sa.text("""
            INSERT INTO clinician_affiliations (
                id,
                clinician_id,
                org_id,
                in_person_sessions,
                virtual_sessions,
                accepts_out_of_network,
                in_network_carriers,
                sliding_scale,
                cost,
                location_city,
                location_state,
                location_zip
            ) VALUES (
                :id,
                :clinician_id,
                NULL,
                NULL,
                NULL,
                1,
                '[]',
                0,
                NULL,
                NULL,
                NULL,
                NULL
            )
            """),
        [
            {"id": str(uuid.uuid4()), "clinician_id": str(row.id)}
            for row in unaffiliated
        ],
    )


def downgrade() -> None:
    """Data-only migration: leave the stub rows in place on downgrade.
    Deleting them on downgrade would be data loss for any user who has
    since edited their posture on the stub. The schema migration that
    follows this one (downgrading past ``82b7dce71362``) will fail on
    its NOT NULL restore if stubs remain — that's the documented
    expected behavior of the schema downgrade.
    """
