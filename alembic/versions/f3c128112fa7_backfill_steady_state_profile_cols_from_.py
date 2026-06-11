"""backfill steady-state profile cols from opening_details and intake_details (PR-f sub-1)

Sibling data migration to ``e3e0a73e9bc5`` (the schema add for the
#1358 PR-f normalization). Copies the per-announcement profile columns
that used to live on ``opening_details`` / ``intake_details`` onto the
*steady-state* homes (``clinician_affiliations`` / ``clinicians`` /
``programs``) so that when sub-PR 2 flips reads, every existing row
has the data the new read site expects.

Backfill rules (deliberately conservative — we do not want to lose or
silently overwrite data):

- **``clinician_affiliations``**: for each affiliation row, find the
  most-recent ``opening_details`` row (by joined post ``created_at``)
  attached either via ``clinician_affiliation_id`` (preferred —
  explicit context) or, when that is NULL, via ``clinician_id`` when
  the clinician has exactly one affiliation (unambiguous attribution).
  Copy ``services`` / ``settings`` / ``modalities`` / ``age_groups`` /
  ``genders`` / ``website`` / ``referral_instructions``. Skip rows
  with no matching opening (leave the schema defaults).
- **``clinicians.languages``**: for each clinician with at least one
  ``opening_details`` row, copy ``languages`` from the most-recent
  such row. Clinicians with no openings keep the default ``["en"]``.
- **``programs``**: same shape as affiliations but via
  ``intake_details.program_id`` (which is NOT NULL — every intake
  detail is tied to a program). Copy the same field set plus
  ``languages`` (Program-level on this side).
- **``currently_accepting_new_patients``** stays False everywhere —
  post lifecycle state is deliberately excluded from #1358 per the
  issue header; we have no signal here to toggle the cache. Sub-PR 2
  wires the lifecycle handlers that flip it.

Downgrade is a no-op. The columns themselves are dropped by the
schema migration above; deleting copies of data we backfilled in
isn't useful — the rows we wrote to don't store anything else lost
on downgrade. (Same shape as ``9501786659b3``'s "leave the stub
rows" rationale.)

Revision ID: f3c128112fa7
Revises: e3e0a73e9bc5
Create Date: 2026-06-10 20:43:48.058645

"""

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c128112fa7"
down_revision: Union[str, None] = "e3e0a73e9bc5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columns copied from opening_details → clinician_affiliations, in
# parallel from intake_details → programs.
_AFFILIATION_COLS = (
    "services",
    "settings",
    "modalities",
    "age_groups",
    "genders",
    "website",
    "referral_instructions",
)


def _is_text(col: str) -> bool:
    return col in ("website", "referral_instructions")


def _backfill_affiliations(bind) -> None:
    """For each ClinicianAffiliation, pick the most-recent OpeningDetail
    that names it (directly via ``clinician_affiliation_id``, or
    indirectly when the clinician has a single affiliation), and copy
    the profile columns over.
    """
    rows = bind.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    od.post_id,
                    od.services,
                    od.settings,
                    od.modalities,
                    od.age_groups,
                    od.genders,
                    od.website,
                    od.referral_instructions,
                    COALESCE(
                        od.clinician_affiliation_id,
                        (
                            SELECT ca.id
                              FROM clinician_affiliations ca
                             WHERE ca.clinician_id = od.clinician_id
                             GROUP BY ca.clinician_id
                            HAVING COUNT(*) = 1
                             LIMIT 1
                        )
                    ) AS affiliation_id,
                    p.created_at AS post_created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(
                            od.clinician_affiliation_id,
                            (
                                SELECT ca.id
                                  FROM clinician_affiliations ca
                                 WHERE ca.clinician_id = od.clinician_id
                                 GROUP BY ca.clinician_id
                                HAVING COUNT(*) = 1
                                 LIMIT 1
                            )
                        )
                        ORDER BY p.created_at DESC, od.post_id DESC
                    ) AS rn
                  FROM opening_details od
                  JOIN posts p ON p.id = od.post_id
            )
            SELECT
                affiliation_id,
                services,
                settings,
                modalities,
                age_groups,
                genders,
                website,
                referral_instructions
              FROM ranked
             WHERE rn = 1
               AND affiliation_id IS NOT NULL
            """)).all()

    for row in rows:
        params = {"id": str(row.affiliation_id)}
        sets = []
        for col in _AFFILIATION_COLS:
            value = getattr(row, col)
            if value is None:
                continue
            if _is_text(col):
                # Text columns: pass through.
                params[col] = value
            else:
                # JSON columns: SQLAlchemy returns the deserialized
                # Python object on SQLite (the column type is JSON).
                # Re-serialize so the bind parameter is a JSON string
                # the JSON column will accept on either dialect.
                if not isinstance(value, str):
                    value = json.dumps(value)
                params[col] = value
            sets.append(f"{col} = :{col}")
        if not sets:
            continue
        bind.execute(
            sa.text(
                f"UPDATE clinician_affiliations SET {', '.join(sets)} WHERE id = :id"
            ),
            params,
        )


def _backfill_clinician_languages(bind) -> None:
    """Copy ``languages`` from the most-recent OpeningDetail per
    clinician onto ``clinicians.languages``.
    """
    rows = bind.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    od.clinician_id,
                    od.languages,
                    p.created_at AS post_created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY od.clinician_id
                        ORDER BY p.created_at DESC, od.post_id DESC
                    ) AS rn
                  FROM opening_details od
                  JOIN posts p ON p.id = od.post_id
            )
            SELECT clinician_id, languages
              FROM ranked
             WHERE rn = 1
            """)).all()

    for row in rows:
        value = row.languages
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value)
        bind.execute(
            sa.text("UPDATE clinicians SET languages = :languages WHERE id = :id"),
            {"id": str(row.clinician_id), "languages": value},
        )


def _backfill_programs(bind) -> None:
    """For each Program, copy the profile columns from the most-recent
    IntakeDetail attached to it.
    """
    rows = bind.execute(sa.text("""
            WITH ranked AS (
                SELECT
                    idtl.program_id,
                    idtl.services,
                    idtl.settings,
                    idtl.modalities,
                    idtl.age_groups,
                    idtl.genders,
                    idtl.languages,
                    idtl.website,
                    idtl.referral_instructions,
                    p.created_at AS post_created_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY idtl.program_id
                        ORDER BY p.created_at DESC, idtl.post_id DESC
                    ) AS rn
                  FROM intake_details idtl
                  JOIN posts p ON p.id = idtl.post_id
            )
            SELECT
                program_id,
                services,
                settings,
                modalities,
                age_groups,
                genders,
                languages,
                website,
                referral_instructions
              FROM ranked
             WHERE rn = 1
            """)).all()

    program_cols = _AFFILIATION_COLS + ("languages",)
    for row in rows:
        params = {"id": str(row.program_id)}
        sets = []
        for col in program_cols:
            value = getattr(row, col)
            if value is None:
                continue
            if _is_text(col):
                params[col] = value
            else:
                if not isinstance(value, str):
                    value = json.dumps(value)
                params[col] = value
            sets.append(f"{col} = :{col}")
        if not sets:
            continue
        bind.execute(
            sa.text(f"UPDATE programs SET {', '.join(sets)} WHERE id = :id"),
            params,
        )


def upgrade() -> None:
    bind = op.get_bind()
    _backfill_affiliations(bind)
    _backfill_clinician_languages(bind)
    _backfill_programs(bind)


def downgrade() -> None:
    """No-op. The schema migration above drops the columns the
    backfill wrote into; there is nothing meaningful to reverse here.
    """
