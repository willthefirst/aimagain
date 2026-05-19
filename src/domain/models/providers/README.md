# Providers cluster: provider + credential sub-records

This subdirectory holds the SQLAlchemy models for the long-lived provider directory entry and its three credential sub-record types. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the provider cluster.

A `Provider` is **not** the same thing as a `OpeningDetail`. They live in different clusters for a reason:

- `Provider` (here, `provider.py`) — long-lived directory entry describing the provider themselves: practice info, location, session-availability flags, and three credential lists. A user may own zero, one, or many.
- `OpeningDetail` ([`../posts/opening_detail.py`](../posts/opening_detail.py)) — per-`Post` detail row for a specific outreach post (`kind = 'opening'`). 1:1 with its parent `Post`; ephemeral relative to a `Provider`.

## Files

- `provider.py` — `Provider`. After #635 PR B `providers` is a thin structural table: `id`, `owner_id` (non-unique FK to `users`, CASCADE — the original `uq_provider_profiles_user_id` was dropped in `8f20a93effc9` so a user may own multiple Providers), `clinician_id` (non-UNIQUE FK to `clinicians`, RESTRICT — multiple providers can share a person), and the audit timestamps. Every per-role attribute (`org_id`, the `(city, state, zip)` triple, `in_person_sessions`, `virtual_sessions`, the insurance posture, `sliding_scale`, `cost`) lives on the linked [`Affiliation`](../affiliations/affiliation.py) rows — **1:N after #642 PR 1** (the UNIQUE on `affiliations.provider_id` was dropped). The `Provider` class exposes the relationship as `provider.affiliations` (ordered by `Affiliation.created_at`) and surfaces a `primary_affiliation` `@property` that returns the oldest row. The per-role attributes are still `@property` proxies — they read and write through `provider.primary_affiliation`, so `repo.patch(provider, location_city="X")` and `ProviderRead.model_validate(provider)` (via `from_attributes`) keep working unchanged. The constructor auto-creates a fresh `Clinician` from any wire-side `npi` kwarg (#629 PR 1) and auto-builds a transient `Affiliation` (the primary one) from any per-role kwargs so the framework's generic create handler (`spec.model(**payload.model_dump())`) still produces fully-wired rows. Additional Affiliations are added later via the inline list on the edit page (`/providers/{id}/affiliations` — see [`../../specs/affiliation.py`](../../specs/affiliation.py)). Credential sub-rows are person-level (FK to `clinicians.id`, #635 PR A); `provider.licensures` / `.educations` / `.certifications` survive as `@property` proxies that delegate to `provider.clinician.licensures` etc. Appending into the proxy returns SQLAlchemy's `InstrumentedList` so the framework's `repo.add_child(parent, "licensures", row)` continues to set `row.clinician_id` automatically. See [`../clinicians/clinician.py`](../clinicians/clinician.py) for the person-attribute home and the NPI format CHECK; see [`../affiliations/affiliation.py`](../affiliations/affiliation.py) for the per-role columns, their CHECK constraints, and the `LocationMixin` join.
- `provider_licensure.py` — `ProviderLicensure`. One row per professional license held by a clinician. CASCADE on the parent FK (`clinician_id`) keeps the credential list in lockstep with the `Clinician`. `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `provider_education.py` — `ProviderEducation`. One row per educational credential. CASCADE on the parent FK (`clinician_id`). `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` is `Text` storing `"YYYY-MM"` rather than a `Date` — the form captures month precision only.
- `provider_certification.py` — `ProviderCertification`. One row per professional certification. CASCADE on the parent FK (`clinician_id`). `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_provider_models.py` — direct DB-layer coverage of the cluster. See the file for the exact assertions; test names are the source of truth.
- `test_provider_enums.py` — guardrail asserting every value in the credential vocabularies (`LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES`) has a matching entry in its `*_LABELS` dict in [`../enums.py`](../enums.py). The form-render macros look up labels by value at request time; missing keys would 500 the request.

## Why this cluster, not flat siblings

Before this extraction the four model files were flat siblings of the rest of `src/domain/models/`. They behaved as one cluster the directory didn't reflect:

- `provider.py` carries the user-facing `@property` proxies — `provider.licensures` / `.educations` / `.certifications` delegate to `provider.clinician.X` (credentials are person-level after #635 PR A), and `provider.org_id` / `.location_*` / `.in_person_sessions` / `.virtual_sessions` / the insurance posture / `.sliding_scale` / `.cost` delegate to `provider.primary_affiliation.X` (per-role columns moved to `affiliations` in #635 PR B; after #642 PR 1 a Provider may hold multiple Affiliations and the proxies target the primary). The actual `relationship(...)` declarations and storage live on `Clinician` and `Affiliation`; Provider keeps the proxy properties so route handlers and templates keep their existing `provider.<attr>` shape.
- `provider_licensure.py`, `provider_education.py`, `provider_certification.py` each carry a `clinician_id` FK back to `clinicians` with `ondelete="CASCADE"` — credentials follow the person, not the Provider directory entry (#635 PR A).
- All four share the table-CHECK pattern (CHECK rendered from a tuple in `../enums.py` via `check_in_tuple_sql`).

Pulling them into `providers/` makes the boundary explicit. The cross-cluster shared modules (the controlled-vocabulary tuples in [`../enums.py`](../enums.py), the `BaseModel` in [`src/framework/persistence/base_model.py`](../../../framework/persistence/base_model.py)) stay at the parent level because the `posts/` cluster also consumes them.

## `provider.org_id` and the practice's display name

A Provider's `primary_affiliation` belongs to exactly one Org, and `provider.org.name` is that Org's display name. Post-#635 PR B `provider.org_id` is a `@property` over `provider.primary_affiliation.org_id` — the FK actually lives on `affiliations.org_id` (NOT NULL, RESTRICT). After #642 PR 1 a Provider may hold additional Affiliations at other Orgs; templates that need the full list iterate `provider.affiliations`. Templates that still read "the" org per-row (the directory listing today; #642 PR 3 collapses that to one row per Clinician) read `provider.org.name` via the property proxy. There is no separate `practice_name` column.

History (Org/Provider roadmap):
- **PR 1 (#516 / #517)** introduced `Organization` as a standalone entity.
- **PR 2 (#520 / #523)** added `Provider.org_id` and kept `Provider.practice_name` as a denormalized mirror of `org.name` to avoid touching ~100+ readers in the same PR.
- **PR 3 (#524)** dropped `Provider.practice_name` and switched every reader to `provider.org.name` — the mirror is gone; `Organization.name` is the sole source of truth.
- **#629 PR 2** introduced `Affiliation` and backfilled one row per Provider, duplicating `org_id` (+ the other per-role columns) onto the new table.
- **#635 PR B** dropped the per-role columns (including `org_id`) from `providers` — `affiliations.org_id` is now the single source of truth and `Provider` accesses it via property proxy.
- **#642 PR 1** dropped the UNIQUE on `affiliations.provider_id` and exposed `provider.affiliations` as a 1:N collection. The `@property` proxies now target `provider.primary_affiliation` (oldest by `created_at`).

**Attaching a Provider to an Org.** The provider create/edit form picks from a dropdown of the **Orgs the requesting user owns** (superusers see every Org). The wire enforces the same boundary: `POST /providers` and `PATCH /providers/{id}` reject an `org_id` that points at an Org the requesting user doesn't own — 403 if it exists, 404 if it doesn't (no leak of other users' Org ids). A user who needs to attach to an Org they don't own must first be granted ownership (invite/grant flow not yet built; for now, create your own Org via `/organizations/form`).

The check lives in `_assert_provider_payload_org_ownership` ([`../../logic/providers/handlers.py`](../../logic/providers/handlers.py)) — bound to `PROVIDER_ENTITY.payload_authz_path` so the framework's factory-built create / update handlers invoke it automatically (#532). The dropdown is scoped by `_orgs_visible_to(...)` in the same module. This matches the `OWNER_OR_ADMIN` policy on the Org row itself — attaching a Provider is effectively writing to the Org's Provider list, so the same boundary applies.

## Adding a new credential sub-record type

If the `Provider` directory entry needs a fourth credential category (e.g. board certifications distinct from professional certifications, malpractice insurance records, etc.):

1. Add a new file `provider_<credential>.py` here. Follow the shape of `provider_certification.py`: extends `BaseModel`, has a `clinician_id` FK to `clinicians` with CASCADE (credentials are person-level — #635 PR A), enum columns CHECK against tuples in `../enums.py`.
2. Add a `relationship("Provider<Credential>", cascade="all, delete-orphan", lazy="selectin")` line on `Clinician`, plus a `@property` proxy on `Provider` returning `self.clinician.<credential>s` so existing call sites keep working.
3. Re-export the new class from [`../__init__.py`](../__init__.py).
4. Add a controlled-vocabulary tuple + label dict to `../enums.py` if the new record introduces one.
5. Generate an Alembic migration for the new table.

The full cross-layer recipe (Pydantic schemas, repository, logic handler, route, template) for a new resource lives in [`src/README.md`](../../../README.md#adding-a-new-domain-entity); the model-layer steps above are the slice that lives in this directory.
