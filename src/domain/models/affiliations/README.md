# Affiliations cluster

The clinician's role at one organization — practice-role attributes that vary per (clinician × org): insurance posture, sliding-scale flag, cost, location, modality.

`Affiliation` was carved out of [`../providers/provider.py`](../providers/provider.py) over the multi-PR `Provider → Clinician + Affiliation` split (issues #629 and #635). #629 PR 2 added the table and backfilled one row per `Provider`. #629 PR 3 switched the directory's read path onto `provider.affiliation.*` ([`../../logic/providers/view.py`](../../logic/providers/view.py)). **#635 PR B is the cleanup that retired the duplicated columns from `providers` and made `affiliations` the single source of truth**: the per-role columns no longer live on `providers` at all, the SQLAlchemy `set`-event mirror listener is gone, and `Provider.X` is now a `@property` over `provider.affiliation.X` (read and write).

See [`../clinicians/README.md`](../clinicians/README.md) for the person side and [`../providers/README.md`](../providers/README.md) for the structural-only cluster the split came out of.

## Files

- `affiliation.py` — `Affiliation`. Holds the per-role columns: `(location_city, location_state, location_zip)` via `LocationMixin`, `in_person_sessions`, `virtual_sessions`, `accepts_out_of_network`, `in_network_carriers`, `sliding_scale`, `cost`. FKs: `clinician_id` (RESTRICT) is the person; `org_id` (RESTRICT) is the organization; `provider_id` (CASCADE, UNIQUE) is the transitional 1:1 link back to the `providers` row — kept because the directory still navigates `provider.affiliation` from a `Provider` instance. The natural next cleanup (if `providers` ever drops to a view or gets renamed) is to retarget that FK at `clinicians.id` and drop this column. `(clinician_id, org_id)` is not UNIQUE: one clinician can hold multiple affiliations at the same org with different attributes (different rate / schedule / location), and the curation rule belongs in business logic, not the schema.
- `test_affiliation.py` — model-layer regression coverage (auto-create-on-Provider-init, skip-when-supplied, per-role writes land on affiliation via the `Provider` property setters, persists-via-cascade).

## Write path: how a Provider edit lands on Affiliation

Provider create and update both target affiliation directly:

- **Create**: the framework's generic create handler calls `Provider(**payload.model_dump())`. `Provider.__init__` peels the per-role kwargs (`org_id`, `location_*`, sessions, insurance posture, `sliding_scale`, `cost`) off `kwargs` and forwards them into a transient `Affiliation` attached as `provider.affiliation`. The structural Provider constructor sees only `owner_id` (and `clinician_id` if the caller pre-wired one). `cascade="all, delete-orphan"` on the `Provider.affiliation` relationship flushes both rows together.
- **Update**: `repo.patch(provider, location_city="X")` calls `setattr(provider, "location_city", "X")`, which hits the `@property` setter on the `Provider` class and writes through to `provider.affiliation.location_city`. No mirror listener required — there's only one place the value lives.
