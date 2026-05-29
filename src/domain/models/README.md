# Models

SQLAlchemy classes only — no business logic, no API serialization. One cluster directory per entity; `ls` is the registry.

## Cluster rule

A model in cluster A does not import from cluster B. Shared primitives hoist to the parent level (`enums.py`, the framework's `BaseModel`). Cross-cluster FKs use SQLAlchemy string references, not Python imports. Enforced by [`../../../scripts/dev/python_cluster_imports_check.py`](../../../scripts/dev/python_cluster_imports_check.py).

## Parent-level shared

- `labeled_choice.py` — `LabeledChoice`, the base type for a controlled vocabulary: an `enum.StrEnum` subclass whose members declare value + label + optional icon together, with `.values()/.labels()/.choices()/.icons()` deriving the artifacts Pydantic `Literal`, DB `CHECK`, seed pools, and Jinja form macros consume. Members ARE `str`, so a vocabulary migrated from a bare tuple/dict pair stays byte-identical on the wire and in storage. A *leaf* (stdlib only). This is the single-source-of-truth shape vocabularies should use; the parallel-`tuple`+`dict` form in `enums.py` is the legacy shape being migrated onto it.
- `enums.py` — controlled-vocabulary tuples + `*_LABELS` dicts + `*_ICONS` dicts (Lucide icon names, consumed by listing-row macros) + `check_in_tuple_sql`. Single source of truth that Pydantic `Literal[*TUPLE]`, Jinja form macros, and DB `CHECK` constraints all derive from. A *leaf* (no internal imports) so any cluster can import without cycling. Both `*_LABELS` and `*_ICONS` are keyed by the storage value, so renaming a *label* doesn't propagate; renaming an *enum value* touches the tuple, the labels dict, and the icons dict in lockstep (guardrail tests in the relevant `test_schema.py` fail if any goes missing). New vocabularies should prefer `LabeledChoice`; vocabularies here derive their tuple/dict aliases from it as they migrate.
- `__init__.py` — re-exports model classes and the framework primitives (`Base`, `BaseModel`, `metadata`) from [`../../framework/`](../../framework/) so external code can always say `from src.domain.models import ...`. The `AuditLog` model is framework-owned and imported directly from [`../../framework/audit/log.py`](../../framework/audit/log.py).

## Polymorphic entities (the post-shape)

When an entity has variants whose fields differ, the parent table carries identity + a discriminator column; each variant's fields live in its own detail table keyed by `<parent>_id` (PK + FK with `ON DELETE CASCADE`). The registry of variants is a `DiscriminatorRegistry[<Spec>]` instance under the parent's cluster (see [`posts/post_kinds.py`](posts/post_kinds.py)). Routes, repositories, and logic are registry-driven — no `isinstance` ladders.

## Foreign-key relationship coverage

Every domain-edge `ForeignKey` MUST have a covering `relationship(...)` at one end. Without it, SQLAlchemy's flush-ordering graph has no signal to flush parent before child, and SQLite with `PRAGMA foreign_keys = ON` rejects the out-of-order INSERT. Denormalized historical references (e.g. `audit_log.actor_id`) opt out via `ALLOWED_BARE_FKS` in [`test_fk_relationship_coverage.py`](test_fk_relationship_coverage.py) with a one-line justification — the justification is half the point.

## Schema changes

Generate an Alembic migration in the same change. See [`../../../alembic/README.md`](../../../alembic/README.md).
