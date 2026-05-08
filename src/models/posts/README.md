# Posts cluster: parent + per-kind detail models

This subdirectory holds the SQLAlchemy models for the `posts` table and its per-kind detail tables, plus the registry that ties them together. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the posts cluster.

## Files

- `post.py` — `Post`, the parent table for any post-shaped resource. Carries identity, ownership, timestamps, and the `kind` discriminator. The `ck_posts_kind` CHECK constraint is rendered from `kind_check_sql()` in `post_kinds.py`. Adding a kind means adding a registry entry and a `relationship(...)` line to `Post`.
- `post_kinds.py` — `REGISTERED_KINDS`, the single source of truth for the kind set. Each `KindSpec` records the kind name, its detail-model class, the relationship attribute on `Post`, the detail row's user-facing field tuple (derived from the model's columns via `_detail_fields(model)`), the create/edit template paths, and the user-facing list label. Every cross-cutting site reads from this registry — see [`../README.md` § "The `post_kinds` registry"](../README.md#the-post_kinds-registry) for the full list.
- `client_referral_detail.py` — `ClientReferralDetail`, the detail row for `kind='client_referral'`. 1:1 with `posts` via `post_id` (PK + FK with CASCADE). Columns track [`notes/forms_spec.md`](../../../notes/forms_spec.md) Form 1; enum columns CHECK against tuples in [`../enums.py`](../enums.py); the `desired_times` and `services` JSON multi-selects have their vocabularies enforced on the wire by Pydantic (no SQL CHECK against array members).
- `provider_availability_detail.py` — `ProviderAvailabilityDetail`, the detail row for `kind='provider_availability'`. Same shape as `ClientReferralDetail` but tracks Form 2; adds the `settings` JSON multi-select. `services` and `settings` are required-min-1 on the wire (vs. optional/absent on Client Referral).
- `test_post_kinds.py` — guardrail tests for the registry as the single source of truth. Asserts `KIND_NAMES` matches the registry, the rendered `kind_check_sql()` matches what `Post.__table_args__` actually produces, the route's `Literal[*KIND_NAMES]` is in lockstep, the inverse `KIND_BY_DETAIL_MODEL` lookup is well-formed, the per-kind relationship-name convention holds, and `KindSpec.detail_fields` matches the detail-model column list exactly. If anyone re-encodes the kind set inline somewhere, one of these tests fails.

## Why this cluster, not flat siblings

Before this extraction, `post.py`, `post_kinds.py`, and the two detail files lived alongside `provider.py`, `provider_licensure.py`, etc. as siblings of one flat `src/models/`. They formed a cluster the directory didn't reflect:

- `post.py` imports from `post_kinds.py`.
- `post_kinds.py` imports from `client_referral_detail.py` and `provider_availability_detail.py`.
- The two detail files share a common table-CHECK pattern, both depend on the same `enums.py` vocabularies.

Pulling them into `posts/` makes the boundary explicit: a reader landing here finds the entire posts data model in one place. Cross-domain shared modules (the controlled-vocabulary tuples in `../enums.py`, the `BaseModel` in `../base.py`) stay at the parent level because they're consumed by the providers cluster too.

## Adding a new kind

The full cross-layer recipe lives in [`../../README.md`](../../README.md#adding-a-new-domain-entity); the model-layer steps for a new kind are:

1. Add a new detail model file `<kind>_detail.py` in this directory. Follow the shape of `client_referral_detail.py`: 1:1 with `posts` via `post_id` PK+FK with CASCADE, enum columns CHECK against tuples in `../enums.py` via `check_in_tuple_sql`.
2. Add a `relationship("<KindDetail>", uselist=False, cascade="all, delete-orphan", lazy="selectin")` line on `Post` in `post.py`.
3. Add a `KindSpec` entry to `REGISTERED_KINDS` in `post_kinds.py`. The `detail_fields` tuple is derived from the model's columns automatically; you only supply the name, detail class, relationship attribute, label, and template paths.
4. Re-export the new detail class from `../__init__.py`.
5. Generate an Alembic migration for the new detail table and the widened `posts.kind` CHECK.

The remaining layers (Pydantic schemas, repository dispatch, logic handlers, route Literal, templates) are all registry-driven — `test_post_kinds.py` will fail loudly if any of them drifts from `REGISTERED_KINDS`.

## Removing a kind

Inverse: delete the registry entry, the detail model file, the `relationship(...)` line on `Post`, the four Pydantic variant classes in `src/schemas/post.py`, the per-kind templates under `src/templates/posts/`, and ship a migration that drops the detail table and narrows the CHECK. No edits in routes, repositories, or logic — see [`../../api/routes/posts.py`](../../api/routes/posts.py) and the dispatch ladders in [`../../logic/post_processing.py`](../../logic/post_processing.py); both read from the registry. The retired `note` kind (removed in migration `c2d3e4f5a6b7`) is the canonical example of how clean this is when the registry is the only source of truth.
