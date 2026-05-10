# Schemas: Request/response validation and serialization

The `schemas/` directory contains **Pydantic schemas** that define the structure and validation rules for API requests and responses.

## Layer organization

Schemas follow the [cluster pattern](../README.md#domain-entities-and-the-cluster-pattern):

- One cluster directory per domain entity (`<entity>/`). Each holds the Pydantic Create / Update / Read / AuditSnapshot variants for that entity (and its sub-entities, if any), plus the colocated test file. Per-entity specifics — discriminator unions, controlled-vocabulary fields, embedded sub-entities — live inside the cluster, with a `<entity>/README.md` if anything is non-obvious.
- Parent-level shared tier (`_validators.py`) — `Annotated[T, AfterValidator(fn)]` aliases and helpers used by 2+ clusters. Add to it when a primitive is used by 2+ schema modules, or when two modules are about to define near-duplicates of the same helper. An alias may also attach an `HtmlPattern(pattern=..., maxlength=...)` marker (from [`src/core/form_fields.py`](../core/form_fields.py)) when the alias's regex/length constraint should also be exposed as the form's client-side `pattern`/`maxlength` — keeps both surfaces aligned at the alias's definition site rather than duplicated per template.

A schema cluster does not import from a peer cluster; cross-cluster reuse happens via the shared tier ([lint-enforced](../README.md#domain-entities-and-the-cluster-pattern)).

The labels-vs-tuple guardrail (`test_schema_literals_match_model_tuples`) lives alongside each cluster's tests; it asserts the cluster's `Literal[*TUPLE]` types stay aligned with the source-of-truth tuples in [`src/models/enums.py`](../models/enums.py).

## Naming

The conventions are visible in the existing schemas (`ClientReferralCreate`, `ClientReferralRead`, `ClientReferralUpdate`, `ClientReferralAuditSnapshot`, etc.). The User cluster follows fastapi-users' `UserRead` / `UserCreate` / `UserUpdate` shape. Match the surrounding cluster when adding a new schema.

## Tests

Each cluster owns its colocated `test_*.py`. See `posts/test_post.py` and `providers/test_provider.py` for the existing examples; their test names are the source of truth for what's covered.

Add `src/schemas/<entity>/test_<file>.py` when a schema has non-trivial validators or computed fields whose behavior isn't obvious from the field definitions.

## Related documentation

- [API Routes](../api/routes/README.md) — routes that use these schemas for validation
- [Models Layer](../models/README.md) — database models that schemas serialize
- [API Layer](../api/README.md) — overall API architecture
