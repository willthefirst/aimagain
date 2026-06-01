# Affiliations cluster

The clinician's role at one organization — practice-role attributes that vary per (clinician × org): insurance posture, sliding-scale flag, cost, location, modality.

`ClinicianAffiliation` was carved out of the former `providers` table over the multi-PR `Provider → Clinician + ClinicianAffiliation` split (issues #629 and #635). After #642 PR 1, `affiliations.clinician_id` is the canonical owner FK, and a clinician may carry multiple affiliations (1:N). See [`../clinicians/README.md`](../clinicians/README.md) for the person side.

## Files

- `affiliation.py` — `ClinicianAffiliation`. Holds the per-role columns: `(location_city, location_state, location_zip)` via `LocationMixin`, `in_person_sessions`, `virtual_sessions`, `accepts_out_of_network`, `in_network_carriers`, `sliding_scale`, `cost`. FKs: `clinician_id` (RESTRICT) is the person; `org_id` (RESTRICT) is the organization. The relationship is 1:N — one clinician may carry multiple affiliations. `(clinician_id, org_id)` is not UNIQUE: one clinician can hold multiple affiliations at the same org with different attributes (different rate / schedule / location), and the curation rule belongs in business logic, not the schema.
- `test_affiliation.py` — model-layer regression coverage (multi-affiliation support, per-role writes, persists-via-cascade).

## Write path: how a clinician edit lands on ClinicianAffiliation

- **Create clinician**: the framework's generic create handler calls `Clinician(**payload.model_dump())`. Per-role kwargs (`org_id`, `location_*`, sessions, insurance posture, `sliding_scale`, `cost`) are forwarded into a new `ClinicianAffiliation` appended onto `clinician.clinician_affiliations`. `cascade="all, delete-orphan"` on the relationship flushes both rows together.
- **Add a second ClinicianAffiliation**: `POST /clinicians/{id}/clinician_affiliations` with the per-role fields. The framework constructs `ClinicianAffiliation(**payload.model_dump())`; the new row sits alongside the existing one(s).
- **Remove an ClinicianAffiliation**: `DELETE /clinicians/{id}/clinician_affiliations/{aff_id}` removes the row through the framework's generic delete handler.
