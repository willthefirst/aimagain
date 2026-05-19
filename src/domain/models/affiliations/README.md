# Affiliations cluster

The clinician's role at one organization — practice-role attributes that vary per (clinician × org): insurance posture, sliding-scale flag, cost, location, modality.

`Affiliation` was carved out of [`../providers/provider.py`](../providers/provider.py) over the four-PR `Provider → Clinician + Affiliation` split (issue #629). PR 2 (this cluster's birth) added the table and backfilled one row per `Provider`. PR 3 switched the directory's read path onto `provider.affiliation.*` ([`../../logic/providers/view.py`](../../logic/providers/view.py) — `_role_attr` reads affiliation-first with a fallback). PR 4 added a SQLAlchemy `set`-event listener on `Provider` that mirrors per-role column writes onto the linked affiliation so the affiliation-first reads see post-edit values.

See [`../clinicians/README.md`](../clinicians/README.md) for the person side and [`../providers/README.md`](../providers/README.md) for the cluster the split came out of.

## Files

- `affiliation.py` — `Affiliation`. Holds the per-role columns mirrored from `providers`: `(location_city, location_state, location_zip)` via `LocationMixin`, `in_person_sessions`, `virtual_sessions`, `accepts_out_of_network`, `in_network_carriers`, `sliding_scale`, `cost`. FKs: `clinician_id` (RESTRICT) is the person; `org_id` (RESTRICT) is the organization; `provider_id` (CASCADE, UNIQUE) is the transitional 1:1 link back to the legacy `providers` row — retired once the column drop on `providers` lands. `(clinician_id, org_id)` is not UNIQUE: one clinician can hold multiple affiliations at the same org with different attributes (different rate / schedule / location), and the curation rule belongs in business logic, not the schema.
- `test_affiliation.py` — model-layer regression coverage (auto-create-on-Provider-init, skip-when-supplied, the per-role write-mirroring event, persists-via-cascade).

## What still lives on `providers`

Through PR 4 the per-role columns are duplicated on `providers` and `affiliations` — `provider_card_view` reads through affiliation; writes hit `providers` and mirror onto affiliation via the `set` event. The remaining cleanup (drop the duplicated columns, switch writes to land directly on affiliation, move credential sub-tables to FK on clinician, rename `Provider → Practice` or its successor) is intentionally deferred to a follow-up issue — each piece is its own contract-surface decision (template hrefs, audit-snapshot keys, URL family) that deserves its own PR.
