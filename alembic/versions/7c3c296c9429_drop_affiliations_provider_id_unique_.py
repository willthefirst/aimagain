"""drop affiliations.provider_id unique constraint

First migration of #642 PR 1 — the directory re-platform's "Provider
holds multiple Affiliations" step. The UNIQUE constraint on
``affiliations.provider_id`` is what pinned the relationship to 1:1
through the #629 / #635 transition; dropping it lets one Provider
carry multiple Affiliation rows (the clinician edit page surfaces
them as an inline list, same UX pattern as licensures).

The FK itself stays (CASCADE on Provider delete). The constraint was
declared as ``unique=True`` on the column at table-create time in
``b2d1c4e8f9a3``, so SQLite renders it as a column-level
``UNIQUE(provider_id)`` clause. SQLAlchemy's reflection-based
``batch_alter_table`` keeps that clause when rewriting unless we pass
a ``copy_from`` table that explicitly redeclares the column without
uniqueness — which is what this migration does.

The downgrade re-establishes the UNIQUE constraint. Any rows that
would violate uniqueness (a Provider with > 1 Affiliation, which
becomes possible after PR 1 ships) cause the rewrite to fail with
``IntegrityError`` — those have to be reconciled by hand before
downgrading, no automatic rule can pick which to keep.

Revision ID: 7c3c296c9429
Revises: d4f7a9b1c6e8
Create Date: 2026-05-19 14:17:29.627430

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c3c296c9429"
down_revision: Union[str, None] = "d4f7a9b1c6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _affiliations_table_without_unique() -> sa.Table:
    """The full ``affiliations`` table reflected from the model, but with
    ``provider_id`` declared without ``unique=True``. ``batch_alter_table``
    consumes this via ``copy_from`` to rewrite SQLite's underlying table
    with the exact column-level constraints we want — reflection alone
    keeps the inline ``UNIQUE(provider_id)`` clause."""

    meta = sa.MetaData()
    return sa.Table(
        "affiliations",
        meta,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
            # No `unique=True` — the whole point of this migration.
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("location_city", sa.Text(), nullable=True),
        sa.Column("location_state", sa.Text(), nullable=True),
        sa.Column("location_zip", sa.Text(), nullable=True),
        sa.Column("in_person_sessions", sa.Text(), nullable=False),
        sa.Column("virtual_sessions", sa.Text(), nullable=False),
        sa.Column(
            "accepts_out_of_network",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "in_network_carriers",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "sliding_scale",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cost", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def _affiliations_table_with_unique() -> sa.Table:
    """Same as :func:`_affiliations_table_without_unique` but with the
    column-level ``unique=True`` restored — for the downgrade path."""

    meta = sa.MetaData()
    return sa.Table(
        "affiliations",
        meta,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("providers.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "clinician_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("clinicians.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("location_city", sa.Text(), nullable=True),
        sa.Column("location_state", sa.Text(), nullable=True),
        sa.Column("location_zip", sa.Text(), nullable=True),
        sa.Column("in_person_sessions", sa.Text(), nullable=False),
        sa.Column("virtual_sessions", sa.Text(), nullable=False),
        sa.Column(
            "accepts_out_of_network",
            sa.Boolean(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "in_network_carriers",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "sliding_scale",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cost", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    """Rewrite ``affiliations`` without the column-level UNIQUE on
    ``provider_id``.

    SQLAlchemy's ``batch_alter_table`` reflects existing constraints
    and re-emits them on the rewritten table. The column-level UNIQUE
    is inline on the ``provider_id`` column, so reflection picks it up
    even if we ``drop_constraint`` it inside the batch. The clean fix
    is ``copy_from=`` — we pass an explicit target table spec without
    ``unique=True`` and ``recreate="always"`` so the rewrite uses our
    shape, not the reflected one.
    """
    with op.batch_alter_table(
        "affiliations",
        copy_from=_affiliations_table_without_unique(),
        recreate="always",
    ) as _:
        pass


def downgrade() -> None:
    """Re-establish the UNIQUE constraint on ``affiliations.provider_id``.

    Raises ``IntegrityError`` if any Provider has more than one
    Affiliation row.
    """
    with op.batch_alter_table(
        "affiliations",
        copy_from=_affiliations_table_with_unique(),
        recreate="always",
    ) as batch_op:
        pass
