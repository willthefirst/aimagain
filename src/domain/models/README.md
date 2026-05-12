# Models

SQLAlchemy classes only — no business logic, no API serialization. One cluster directory per entity; `ls` is the registry.

## Cluster rule

A model in cluster A does not import from cluster B. Shared primitives hoist to the parent level (`enums.py`, the framework's `BaseModel`). Cross-cluster FKs use SQLAlchemy string references, not Python imports. Enforced by [`../../../scripts/dev/python_cluster_imports_check.py`](../../../scripts/dev/python_cluster_imports_check.py).

## Parent-level shared

- `enums.py` — controlled-vocabulary tuples + `*_LABELS` dicts + `check_in_tuple_sql`. Single source of truth that Pydantic `Literal[*TUPLE]`, Jinja form macros, and DB `CHECK` constraints all derive from. A *leaf* (no internal imports) so any cluster can import without cycling.
- `__init__.py` — re-exports model classes and the framework primitives (`Base`, `BaseModel`, `metadata`, `AuditLog`) from [`../../framework/`](../../framework/) so external code can always say `from src.domain.models import ...`.

## Polymorphic entities (the post-shape)

When an entity has variants whose fields differ, the parent table carries identity + a discriminator column; each variant's fields live in its own detail table keyed by `<parent>_id` (PK + FK with `ON DELETE CASCADE`). The registry of variants is a `DiscriminatorRegistry[<Spec>]` instance under the parent's cluster (see [`posts/post_kinds.py`](posts/post_kinds.py)). Routes, repositories, and logic are registry-driven — no `isinstance` ladders.

## Foreign-key relationship coverage

Every domain-edge `ForeignKey` MUST have a covering `relationship(...)` at one end. Without it, SQLAlchemy's flush-ordering graph has no signal to flush parent before child, and SQLite with `PRAGMA foreign_keys = ON` rejects the out-of-order INSERT. Denormalized historical references (e.g. `audit_log.actor_id`) opt out via `ALLOWED_BARE_FKS` in [`test_fk_relationship_coverage.py`](test_fk_relationship_coverage.py) with a one-line justification — the justification is half the point.

## Schema changes

Generate an Alembic migration in the same change. See [`../../../alembic/README.md`](../../../alembic/README.md).
