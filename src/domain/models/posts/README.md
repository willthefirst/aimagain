# Posts cluster: parent + per-kind detail models

This subdirectory holds the SQLAlchemy models for the `posts` table and its per-kind detail tables, plus the registry that ties them together. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the posts cluster.

## Files

- `post.py` — `Post`, the parent table for any post-shaped resource. Carries identity, ownership, timestamps, and the `kind` discriminator. The `ck_posts_kind` CHECK constraint is rendered from `POST_KINDS.check_sql()` in `post_kinds.py`. Adding a kind means adding a registry entry and a `relationship(...)` line to `Post`.
- `post_kinds.py` — `POST_KINDS: DiscriminatorRegistry[PostKindSpec]`, the single source of truth for the kind set. Each `PostKindSpec` records the kind name, its detail-model class, the relationship attribute on `Post`, the detail row's user-facing field tuple (derived from the model's columns via `_detail_fields(model)`), the create/edit template paths, and the user-facing list label. The registry's bookkeeping (`names` tuple, `check_sql()`, reverse indexes) comes from the generic `DiscriminatorRegistry` in [`src/framework/persistence/polymorphic.py`](../../../framework/persistence/polymorphic.py); this file declares only the post-specific Spec shape and the registry instance. Every cross-cutting site reads from this registry — see [`../README.md` § "The `post_kinds` registry"](../README.md#the-post_kinds-registry) for the full list.
- `referral_detail.py` — `ReferralDetail`, the detail row for `kind='referral'`. 1:1 with `posts` via `post_id` (PK + FK with CASCADE). Columns track the client-referral intake form; enum columns CHECK against tuples in [`../enums.py`](../enums.py); the `desired_times` and `services` JSON multi-selects have their vocabularies enforced on the wire by Pydantic (no SQL CHECK against array members). The `(city, state, zip)` triple comes from [`LocationMixin`](../../../framework/persistence/mixins.py) — same mixin `Clinician` uses.
- `opening_detail.py` — `OpeningDetail`, the detail row for `kind='clinician_opening'`. Same shape as `ReferralDetail` but tracks the clinician-availability form; adds the `settings` JSON multi-select. `services` and `settings` are required-min-1 on the wire (vs. optional/absent on Client Referral). Table name stays `opening_details` from before the kind rename (migration `9e1f7b3c4a2d`) — pure rename noise to drop it.
- `intake_detail.py` — `IntakeDetail`, the detail row for `kind='program_intake'` (#541). Same per-announcement field set as `OpeningDetail` but points at a `Program` via `program_id` instead of a `Clinician` — the referrer is choosing an *intake door* (the Program) and trusting the owning Org to assign a clinician internally. Table name stays `intake_details` for the same reason as `opening_details`.

### Listing context (`clinician_affiliation_id`)

The two clinician-authored detail kinds (`OpeningDetail`, `ReferralDetail`) carry a nullable `clinician_affiliation_id` FK → `clinician_affiliations.id` (`ON DELETE SET NULL`): a clinician who affiliates with several orgs (`clinician_affiliations` is 1:N off `clinicians`) declares *which* affiliation a given opening/referral is offered under. It's nullable because the column post-dates existing rows and because not every listing has a context set. `IntakeDetail` has no such column — its context is the `Program`'s owning org, reachable via `program_id`. Migration `c4d5e6f7a8b9` added the columns and backfilled each existing row to its clinician's primary (earliest-`created_at`) affiliation, matching `Clinician.primary_clinician_affiliation`.

On the create/edit forms this column is the **only** clinician selector the user touches: the practice picker submits `clinician_affiliation_id`, and the listing's clinician FK (`referring_clinician_id` for referrals, `clinician_id` for openings) is *derived* from that affiliation server-side — so the two can never disagree, and a clinician affiliated with two orgs no longer collapses both options onto one value. The derivation runs in `_resolve_affiliation_context` ([`../../logic/posts/handlers.py`](../../logic/posts/handlers.py)) before the FK-ownership check, which then validates the resolved clinician.

## Kind name history (audit-log readers)

Audit-log rows persist the kind value that was current when the row was written. Two renames happened in `posts.kind`:

| Migration | Old value | New value |
|---|---|---|
| `e9d8c7b6a5f4` | `provider_availability` | `opening` |
| `e9d8c7b6a5f4` | `client_referral` | `referral` |
| `4a8b2c5d9e1f` | `program_availability` | `intake` |
| `9e1f7b3c4a2d` | `opening` | `clinician_opening` |
| `9e1f7b3c4a2d` | `intake` | `program_intake` |

`audit_log.before` / `audit_log.after` JSON snapshots reference whatever string was current when the row was written; they are intentionally not rewritten. Readers ranging over audit history should expect any of the historical names.
- `test_post_kinds.py` — guardrail tests for the registry as the single source of truth. Asserts `POST_KIND_NAMES` matches the registry, the rendered `POST_KINDS.check_sql()` matches what `Post.__table_args__` actually produces, the route's `Literal[*POST_KIND_NAMES]` is in lockstep, the inverse `POST_KIND_BY_DETAIL_MODEL` lookup is well-formed, the per-kind relationship-name convention holds, and `PostKindSpec.detail_fields` matches the detail-model column list exactly. If anyone re-encodes the kind set inline somewhere, one of these tests fails.

## Why this cluster, not flat siblings

Before this extraction, `post.py`, `post_kinds.py`, and the two detail files lived alongside the former `provider.py` and credential files as siblings of one flat `src/domain/models/`. They formed a cluster the directory didn't reflect:

- `post.py` imports from `post_kinds.py`.
- `post_kinds.py` imports from `referral_detail.py` and `opening_detail.py`.
- The two detail files share a common table-CHECK pattern, both depend on the same `enums.py` vocabularies.

Pulling them into `posts/` makes the boundary explicit: a reader landing here finds the entire posts data model in one place. Cross-domain shared modules (the controlled-vocabulary tuples in `../enums.py`, the `BaseModel` in [`src/framework/persistence/base_model.py`](../../../framework/persistence/base_model.py)) stay at the parent level because they're consumed by the clinicians cluster too.

## Adding a new kind

The full cross-layer recipe lives in [`src/README.md`](../../../README.md#adding-a-new-domain-entity); the model-layer steps for a new kind are:

1. Add a new detail model file `<kind>_detail.py` in this directory. Follow the shape of `referral_detail.py`: 1:1 with `posts` via `post_id` PK+FK with CASCADE, enum columns CHECK against tuples in `../enums.py` via `check_in_tuple_sql`.
2. Add a `relationship("<KindDetail>", uselist=False, cascade="all, delete-orphan", lazy="selectin")` line on `Post` in `post.py`.
3. Add a `PostKindSpec` entry to `POST_KINDS` in `post_kinds.py`. The `detail_fields` tuple is derived from the model's columns automatically; you only supply the name, detail class, relationship attribute, label, and template paths.
4. Re-export the new detail class from `../__init__.py`.
5. Generate an Alembic migration for the new detail table and the widened `posts.kind` CHECK.

The remaining layers (Pydantic schemas, repository dispatch, logic handlers, route Literal, templates) are all registry-driven — `test_post_kinds.py` will fail loudly if any of them drifts from `POST_KINDS`.

## Removing a kind

Inverse: delete the registry entry, the detail model file, the `relationship(...)` line on `Post`, the four Pydantic variant classes in `src/domain/logic/posts/schema.py`, the per-kind templates (all per-kind templates live directly under `src/domain/templates/posts/` following the default `PostKindSpec` convention — no template path overrides), and ship a migration that drops the detail table and narrows the CHECK. No edits in routes, repositories, or logic — see [`../../routes/posts.py`](../../routes/posts.py) and the per-kind schema in [`../../logic/posts/schema.py`](../../logic/posts/schema.py); both read from the registry. The retired `note` kind (removed in migration `c2d3e4f5a6b7`) is the canonical example of how clean this is when the registry is the only source of truth.

## URL faces

A single URL family exposes the supertype:

- **`/posts`** — whole-supertype face listing every kind (`kind ∈ {referral, clinician_opening, program_intake}`). The `?kind=X` query param narrows the list and drives create/edit dispatch to the per-kind detail model and template. Spec: `POST_ENTITY`. See [`src/framework/dispatch/entity_spec.py`](../../../framework/dispatch/entity_spec.py) `discriminator_value` docstring for the face-mode contract.

The previous per-face URL families (`/referrals`, `/openings`, `/intakes`) were collapsed into the single `/posts` face; the kind values survive unchanged, only the URL collection changed.
