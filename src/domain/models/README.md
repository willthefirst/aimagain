# Models

SQLAlchemy classes only — no business logic, no API serialization. One cluster directory per entity; `ls` is the registry.

## Cluster rule

A model in cluster A does not import from cluster B. Shared primitives hoist to the parent level (`enums.py`, the framework's `BaseModel`). Cross-cluster FKs use SQLAlchemy string references, not Python imports. Enforced by [`../../../scripts/dev/python_cluster_imports_check.py`](../../../scripts/dev/python_cluster_imports_check.py).

## Parent-level shared

- `labeled_choice.py` — `LabeledChoice`, the base type for a controlled vocabulary: an `enum.StrEnum` subclass whose members declare value + label + optional icon together, with `.values()/.labels()/.choices()/.icons()` deriving the artifacts Pydantic `Literal`, DB `CHECK`, seed pools, and Jinja form macros consume. Members ARE `str`, so a vocabulary stays byte-identical on the wire and in storage. A vocabulary with richer display facts than value+label+icon (a singular/plural/range cohort, a two-label weekday) subclasses with a custom `__new__` that attaches the extra attributes. A *leaf* (stdlib only). This is the single-source-of-truth shape every labeled vocabulary uses.
- `enums.py` — the project's `LabeledChoice` vocabularies plus their derived `FOO` / `FOO_LABELS` / `FOO_ICONS` aliases (kept so downstream consumers — Pydantic `Literal[*TUPLE]`, Jinja form macros, DB `CHECK` constraints, seed pools — stay unchanged) and `check_in_tuple_sql`. A *leaf* (no internal imports) so any cluster can import without cycling. Because each label/icon derives from its class, renaming an *enum value* touches one member line and the aliases follow automatically. `US_STATES` is the lone plain tuple: a USPS abbreviation is its own label, so there's nothing to single-source. Value freezes and alias-equals-derivation checks live in `test_enums.py`.
- `__init__.py` — re-exports model classes and the framework primitives (`Base`, `BaseModel`, `metadata`) from [`../../framework/`](../../framework/) so external code can always say `from src.domain.models import ...`. The `AuditLog` model is framework-owned and imported directly from [`../../framework/audit/log.py`](../../framework/audit/log.py).

## Polymorphic entities (the post-shape)

When an entity has variants whose fields differ, the parent table carries identity + a discriminator column; each variant's fields live in its own detail table keyed by `<parent>_id` (PK + FK with `ON DELETE CASCADE`). The registry of variants is a `DiscriminatorRegistry[<Spec>]` instance under the parent's cluster (see [`posts/post_kinds.py`](posts/post_kinds.py)). Routes, repositories, and logic are registry-driven — no `isinstance` ladders.

## Steady-state context vs. per-announcement dimensions

When a durable entity posts announcements, each column lives on exactly one side of a split: **steady-state context** — what doesn't change announcement-to-announcement — stays on the durable entity, while **per-announcement dimensions** — anything the same entity could legitimately vary between two simultaneous announcements — live on the announcement's detail row, which is self-describing. The mental model: *steady-state context goes on the durable entity; the announcement describes itself.* Each cluster README documents which of its columns fall on which side.

## Foreign-key relationship coverage

Every domain-edge `ForeignKey` MUST have a covering `relationship(...)` at one end. Without it, SQLAlchemy's flush-ordering graph has no signal to flush parent before child, and SQLite with `PRAGMA foreign_keys = ON` rejects the out-of-order INSERT. Denormalized historical references (e.g. `audit_log.actor_id`) opt out via `ALLOWED_BARE_FKS` in [`test_fk_relationship_coverage.py`](test_fk_relationship_coverage.py) with a one-line justification — the justification is half the point.

## Schema changes

Generate an Alembic migration in the same change. See [`../../../alembic/README.md`](../../../alembic/README.md).
