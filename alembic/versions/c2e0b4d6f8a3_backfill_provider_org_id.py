"""backfill provider.org_id from practice_name

PR 2 of the Org/Program roadmap (#520), data half. Walks the existing
``providers`` rows grouped by ``practice_name``, creates one
``Organization`` per distinct name, points every matching provider at
it, then tightens ``providers.org_id`` to ``NOT NULL``.

Per-group bookkeeping:

* **One Org per distinct ``practice_name``** — the same practice run by
  multiple owners still collapses to a single Org (PR 3 will revisit
  whether that's the right default; today it preserves the "one
  practice, one directory entry" reading users already have).
* **Type:** ``solo_practice`` when the group has exactly one provider,
  ``group_practice`` when it has more. Two tokens covers every existing
  shape; admins can reclassify in PR 3+ once the create form exists.
* **Owner:** the owner of the group's *lowest-``created_at``* provider —
  deterministic so the migration is replayable.
* **Root:** every backfill Org is its own root (``parent_org_id IS NULL``,
  ``root_org_id = id``). Hierarchies are PR 4's concern.

The downgrade defensively refuses if any ``organizations`` row exists
that this migration didn't create (i.e. an Org with no referencing
``providers`` row, or whose ``name`` no longer matches the referencing
providers' ``practice_name``). Mirrors ``e7b3c2a8f1d4``'s pattern:
don't silently destroy data that arrived after the migration.

Revision ID: c2e0b4d6f8a3
Revises: b1f9a3c5d7e2
Create Date: 2026-05-17
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c2e0b4d6f8a3"
down_revision: Union[str, None] = "b1f9a3c5d7e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Walk distinct practice_name values. For each, pick the lowest-
    # created_at provider as the deterministic owner-source, count
    # group size, then create the Org and point every matching row at it.
    groups = bind.execute(sa.text("""
            SELECT practice_name, COUNT(*) AS provider_count
            FROM providers
            WHERE org_id IS NULL
            GROUP BY practice_name
            """)).fetchall()

    for group in groups:
        owner_row = bind.execute(
            sa.text("""
                SELECT owner_id
                FROM providers
                WHERE practice_name = :practice_name AND org_id IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """),
            {"practice_name": group.practice_name},
        ).fetchone()
        assert owner_row is not None  # group came from this same table

        org_type = "solo_practice" if group.provider_count == 1 else "group_practice"
        # SQLite's sqlite3 driver can't bind a uuid.UUID object; the
        # Uuid type stores hex. Use .hex consistently (matches the
        # pattern from 537ba27726f9).
        org_id = uuid.uuid4().hex

        bind.execute(
            sa.text("""
                INSERT INTO organizations (
                    id, name, type, owner_id,
                    parent_org_id, root_org_id,
                    created_at, updated_at
                ) VALUES (
                    :id, :name, :type, :owner_id,
                    NULL, :id,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """),
            {
                "id": org_id,
                "name": group.practice_name,
                "type": org_type,
                "owner_id": owner_row.owner_id,
            },
        )

        bind.execute(
            sa.text("""
                UPDATE providers
                SET org_id = :org_id
                WHERE practice_name = :practice_name AND org_id IS NULL
                """),
            {"org_id": org_id, "practice_name": group.practice_name},
        )

    # Promote org_id to NOT NULL now that every row carries one.
    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("org_id", nullable=False)


def downgrade() -> None:
    """Refuse if any Org exists that this migration didn't create, then
    null out every ``providers.org_id`` and delete the backfill-Orgs.

    "Created by this migration" means: at least one provider currently
    points at the Org via ``org_id`` AND every such provider's
    ``practice_name`` equals the Org's ``name``. Anything else is data
    the migration must not destroy."""
    bind = op.get_bind()

    # Find orgs the backfill couldn't possibly have created in its
    # known shape. Two failure modes:
    #
    #   1) the Org has zero referencing providers (some other writer
    #      created it post-migration);
    #   2) at least one referencing provider's practice_name disagrees
    #      with the Org's name (the mirror has been broken — the
    #      migration's invariant no longer holds for this row).
    suspect_orgs = bind.execute(sa.text("""
            SELECT o.id, o.name
            FROM organizations AS o
            LEFT JOIN providers AS p ON p.org_id = o.id
            GROUP BY o.id, o.name
            HAVING COUNT(p.id) = 0
                OR SUM(CASE WHEN p.practice_name = o.name THEN 0 ELSE 1 END) > 0
            """)).fetchall()
    if suspect_orgs:
        names = ", ".join(f"{row.name!r}" for row in suspect_orgs)
        raise RuntimeError(
            f"cannot downgrade: {len(suspect_orgs)} organization(s) not "
            f"created by this migration: {names}; resolve manually before "
            "downgrading"
        )

    with op.batch_alter_table("providers") as batch_op:
        batch_op.alter_column("org_id", nullable=True)

    # Collect the org IDs we're about to delete BEFORE nulling out the
    # FKs, otherwise the join can't tell us which orgs to drop.
    backfill_org_ids = [
        row.org_id
        for row in bind.execute(
            sa.text("SELECT DISTINCT org_id FROM providers WHERE org_id IS NOT NULL")
        ).fetchall()
    ]

    bind.execute(sa.text("UPDATE providers SET org_id = NULL"))

    if backfill_org_ids:
        bind.execute(
            sa.text("DELETE FROM organizations WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": backfill_org_ids},
        )
