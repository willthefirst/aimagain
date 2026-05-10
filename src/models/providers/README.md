# Providers cluster: provider + credential sub-records

This subdirectory holds the SQLAlchemy models for the long-lived provider directory entry and its three credential sub-record types. The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to the provider cluster.

A `Provider` is **not** the same thing as a `ProviderAvailabilityDetail`. They live in different clusters for a reason:

- `Provider` (here, `provider.py`) — long-lived directory entry describing the provider themselves: practice info, location, session-availability flags, and three credential lists. A user may own zero, one, or many.
- `ProviderAvailabilityDetail` ([`../posts/provider_availability_detail.py`](../posts/provider_availability_detail.py)) — per-`Post` detail row for a specific outreach post (`kind = 'provider_availability'`). 1:1 with its parent `Post`; ephemeral relative to a `Provider`.

## Files

- `provider.py` — `Provider`. Tied to a `User` via non-unique `owner_id` FK + CASCADE (the original `uq_provider_profiles_user_id` was dropped in `8f20a93effc9` to allow multiple `Provider` rows per user). Owns `ProviderLicensure`, `ProviderEducation`, `ProviderCertification` rows via `cascade="all, delete-orphan"` + FK CASCADE — deleting a `Provider` removes the credential lists in one shot. Enum columns CHECK against `US_STATES` and `LOCATION_AVAILABILITY_OPTIONS` from [`../enums.py`](../enums.py).
- `provider_licensure.py` — `ProviderLicensure`. One row per professional license held by a provider. CASCADE on the parent FK keeps the credential list in lockstep with the `Provider`. `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `provider_education.py` — `ProviderEducation`. One row per educational credential. CASCADE on the parent FK. `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` is `Text` storing `"YYYY-MM"` rather than a `Date` — the form captures month precision only.
- `provider_certification.py` — `ProviderCertification`. One row per professional certification. CASCADE on the parent FK. `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_provider_models.py` — direct DB-layer coverage of the cluster. See the file for the exact assertions; test names are the source of truth.
- `test_provider_enums.py` — guardrail asserting every value in the credential vocabularies (`LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES`) has a matching entry in its `*_LABELS` dict in [`../enums.py`](../enums.py). The form-render macros look up labels by value at request time; missing keys would 500 the request.

## Why this cluster, not flat siblings

Before this extraction the four model files were flat siblings of the rest of `src/models/`. They behaved as one cluster the directory didn't reflect:

- `provider.py` declares the parent-side `relationship(...)` for all three sub-record types via `cascade="all, delete-orphan"`.
- `provider_licensure.py`, `provider_education.py`, `provider_certification.py` each carry a `provider_id` FK back to `providers` with `ondelete="CASCADE"` — they have no meaning without a parent `Provider`.
- All four share the table-CHECK pattern (CHECK rendered from a tuple in `../enums.py` via `check_in_tuple_sql`).

Pulling them into `providers/` makes the boundary explicit. The cross-cluster shared modules (the controlled-vocabulary tuples in [`../enums.py`](../enums.py), the `BaseModel` in [`../base.py`](../base.py)) stay at the parent level because the `posts/` cluster also consumes them.

## Adding a new credential sub-record type

If the `Provider` directory entry needs a fourth credential category (e.g. board certifications distinct from professional certifications, malpractice insurance records, etc.):

1. Add a new file `provider_<credential>.py` here. Follow the shape of `provider_certification.py`: extends `BaseModel`, has a `provider_id` FK to `providers` with CASCADE, enum columns CHECK against tuples in `../enums.py`.
2. Add a `relationship("Provider<Credential>", cascade="all, delete-orphan", lazy="selectin")` line on `Provider`.
3. Re-export the new class from [`../__init__.py`](../__init__.py).
4. Add a controlled-vocabulary tuple + label dict to `../enums.py` if the new record introduces one.
5. Generate an Alembic migration for the new table.

The full cross-layer recipe (Pydantic schemas, repository, logic handler, route, template) for a new resource lives in [`../../README.md`](../../README.md#adding-a-new-domain-entity); the model-layer steps above are the slice that lives in this directory.
