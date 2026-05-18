# Providers cluster: provider + credential sub-records

This subdirectory holds the SQLAlchemy models for the long-lived provider directory entry and its three credential sub-record types. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the provider cluster.

A `Provider` is **not** the same thing as a `ProviderAvailabilityDetail`. They live in different clusters for a reason:

- `Provider` (here, `provider.py`) — long-lived directory entry describing the provider themselves: practice info, location, session-availability flags, and three credential lists. A user may own zero, one, or many.
- `ProviderAvailabilityDetail` ([`../posts/provider_availability_detail.py`](../posts/provider_availability_detail.py)) — per-`Post` detail row for a specific outreach post (`kind = 'provider_availability'`). 1:1 with its parent `Post`; ephemeral relative to a `Provider`.

## Files

- `provider.py` — `Provider`. Tied to a `User` via non-unique `owner_id` FK + CASCADE (the original `uq_provider_profiles_user_id` was dropped in `8f20a93effc9` to allow multiple `Provider` rows per user). Owns `ProviderLicensure`, `ProviderEducation`, `ProviderCertification` rows via `cascade="all, delete-orphan"` + FK CASCADE — deleting a `Provider` removes the credential lists in one shot. Enum columns CHECK against `US_STATES` and `LOCATION_AVAILABILITY_OPTIONS` from [`../enums.py`](../enums.py). The `(city, state, zip)` triple comes from [`LocationMixin`](../../../framework/persistence/mixins.py) — same mixin `ClientReferralDetail` uses, so the column declarations stay in lockstep.
- `provider_licensure.py` — `ProviderLicensure`. One row per professional license held by a provider. CASCADE on the parent FK keeps the credential list in lockstep with the `Provider`. `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `provider_education.py` — `ProviderEducation`. One row per educational credential. CASCADE on the parent FK. `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` is `Text` storing `"YYYY-MM"` rather than a `Date` — the form captures month precision only.
- `provider_certification.py` — `ProviderCertification`. One row per professional certification. CASCADE on the parent FK. `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_provider_models.py` — direct DB-layer coverage of the cluster. See the file for the exact assertions; test names are the source of truth.
- `test_provider_enums.py` — guardrail asserting every value in the credential vocabularies (`LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES`) has a matching entry in its `*_LABELS` dict in [`../enums.py`](../enums.py). The form-render macros look up labels by value at request time; missing keys would 500 the request.

## Why this cluster, not flat siblings

Before this extraction the four model files were flat siblings of the rest of `src/domain/models/`. They behaved as one cluster the directory didn't reflect:

- `provider.py` declares the parent-side `relationship(...)` for all three sub-record types via `cascade="all, delete-orphan"`.
- `provider_licensure.py`, `provider_education.py`, `provider_certification.py` each carry a `provider_id` FK back to `providers` with `ondelete="CASCADE"` — they have no meaning without a parent `Provider`.
- All four share the table-CHECK pattern (CHECK rendered from a tuple in `../enums.py` via `check_in_tuple_sql`).

Pulling them into `providers/` makes the boundary explicit. The cross-cluster shared modules (the controlled-vocabulary tuples in [`../enums.py`](../enums.py), the `BaseModel` in [`src/framework/persistence/base_model.py`](../../../framework/persistence/base_model.py)) stay at the parent level because the `posts/` cluster also consumes them.

## The `org_id` + `practice_name` mirror

PR 2 of the Org/Program roadmap (#520). `Provider.org_id` is a NOT NULL FK to `organizations.id` — every Provider belongs to exactly one Org. `Provider.practice_name` exists alongside it as a **denormalized mirror** of `provider.org.name`.

**The invariant: `provider.practice_name == provider.org.name`, for every row, at all times.**

The mirror is enforced in [`../../logic/providers/repository.py`](../../logic/providers/repository.py) (`ProviderRepository.create` / `patch`), mirroring the shape `OrganizationRepository` uses for its own `root_org_id` denormalization (PR 1):

- On `create`: if `org_id` is set, `practice_name` is overwritten from the Org's `name`. If `org_id` is unset (today's wire shape — no Org-picker in the create form yet), the repo find-or-creates an Org keyed on `practice_name` and assigns its id.
- On `patch`: a change to `org_id` rewrites `practice_name` from the new Org; a change to `practice_name` find-or-creates an Org and reassigns `org_id`.

**Why a mirror at all.** Templates, Pydantic schemas, contract tests, and repository queries currently read `provider.practice_name` directly (~100+ call sites). The mirror keeps those callers untouched in PR 2 — the migration vehicle costs one column and one repo override; the alternative was a multi-PR template / schema / contract sweep behind a feature flag.

**Lifetime.** PR 3 of the roadmap drops `practice_name` and switches every reader to `provider.org.name`. The override and this section go with it. The repository override is marked `# TODO(roadmap-pr-3)` so the cleanup is grep-able.

The two columns being required to agree is the only place this codebase deliberately violates the "one source of truth" rule in CLAUDE.md — it's load-bearing only because PR 3 is the next change.

## Adding a new credential sub-record type

If the `Provider` directory entry needs a fourth credential category (e.g. board certifications distinct from professional certifications, malpractice insurance records, etc.):

1. Add a new file `provider_<credential>.py` here. Follow the shape of `provider_certification.py`: extends `BaseModel`, has a `provider_id` FK to `providers` with CASCADE, enum columns CHECK against tuples in `../enums.py`.
2. Add a `relationship("Provider<Credential>", cascade="all, delete-orphan", lazy="selectin")` line on `Provider`.
3. Re-export the new class from [`../__init__.py`](../__init__.py).
4. Add a controlled-vocabulary tuple + label dict to `../enums.py` if the new record introduces one.
5. Generate an Alembic migration for the new table.

The full cross-layer recipe (Pydantic schemas, repository, logic handler, route, template) for a new resource lives in [`src/README.md`](../../../README.md#adding-a-new-domain-entity); the model-layer steps above are the slice that lives in this directory.
