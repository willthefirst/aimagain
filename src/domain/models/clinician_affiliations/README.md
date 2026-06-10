# Affiliations cluster

The clinician's role at one organization — practice-role attributes that vary per (clinician × org): insurance posture, sliding-scale flag, cost, location, modality.

`ClinicianAffiliation` was carved out of the former `providers` table over the multi-PR `Provider → Clinician + ClinicianAffiliation` split (issues #629 and #635). After #642 PR 1, `affiliations.clinician_id` is the canonical owner FK, and a clinician may carry multiple affiliations (1:N). See [`../clinicians/README.md`](../clinicians/README.md) for the person side.

## Files

- `affiliation.py` — `ClinicianAffiliation`. Holds the per-role columns: `(location_city, location_state, location_zip)` via `LocationMixin`, `in_person_sessions`, `virtual_sessions`, `accepts_out_of_network`, `in_network_carriers`, `sliding_scale`, `cost`. FKs: `clinician_id` (RESTRICT) is the person; `org_id` (RESTRICT, **nullable**) is the organization. The relationship is 1:N — one clinician may carry multiple affiliations. `(clinician_id, org_id)` is not UNIQUE: one clinician can hold multiple affiliations at the same org with different attributes (different rate / schedule / location), and the curation rule belongs in business logic, not the schema.
- `test_affiliation.py` — model-layer regression coverage (multi-affiliation support, per-role writes, persists-via-cascade).

## The "every clinician has ≥1 affiliation" invariant

A `ClinicianAffiliation` is the **practice posture container**: it owns location, availability, in-network carriers, and cost. Practice posture genuinely varies per (clinician × context) — the same person can work as a telehealth-only cash-pay clinician in private practice AND as an in-person Aetna-paneled clinician at a group, both at once. So `ClinicianAffiliation` is the unit those vary on, not `Clinician`.

That means every clinician — including a solo practitioner with no LLC and no group — has at least one affiliation. The "solo" case is a `ClinicianAffiliation` row with `org_id IS NULL`: the row carries the practice posture; the absence of an `Organization` reflects that there is no separate legal/branding entity. The `Clinician` proxy properties (`clinician.location_city`, `.in_person_sessions`, etc.) read from / write to this single affiliation; per [`../clinicians/README.md#per-affiliation-proxy-setters-require-a-primary-affiliation`](../clinicians/README.md#per-affiliation-proxy-setters-require-a-primary-affiliation), the setters raise if no affiliation exists.

Sessions columns (`in_person_sessions`, `virtual_sessions`) are also nullable: a stub affiliation auto-created at NPI verify time hasn't yet been asked those questions; NULL means "unset," distinct from any `LOCATION_AVAILABILITY_OPTIONS` value. The auto-create lives in `after_create_clinician_verification` ([`../../logic/clinicians/handlers.py`](../../logic/clinicians/handlers.py)) — the canonical "this clinician is real and going to stick around" moment. The backfill migration `9501786659b3` covers pre-existing solo clinicians.

## Write path: how a clinician edit lands on ClinicianAffiliation

After #1308, practice posture is patched **directly on the affiliation**, not through the clinician's PATCH form: `ClinicianUpdate` accepts only `first_name` / `last_name` / `npi`, and the affiliation owns everything else. The clinician edit page surfaces affiliations as inline rows for create / delete; an inline-edit affordance is the next step.

- **Create clinician**: the framework's generic create handler calls `Clinician(**payload.model_dump())`. If per-role kwargs are supplied (older code paths / tests), they are forwarded into a new `ClinicianAffiliation` appended onto `clinician.clinician_affiliations`; otherwise the verification handler creates a stub with all per-role columns NULL/default. `cascade="all, delete-orphan"` flushes both rows together.
- **Patch a ClinicianAffiliation's posture**: `PATCH /clinicians/{id}/clinician_affiliations/{aff_id}` with the per-role fields. Mounted via the framework's generic sub-resource update handler against `ClinicianAffiliationUpdate`. This is the canonical write path for posture after #1308.
- **Add a second ClinicianAffiliation**: `POST /clinicians/{id}/clinician_affiliations`. `ClinicianAffiliationCreate` is fully optional after PR-7, so the inline "Add another practice" form on the clinician edit page can create a solo (no-org) row by leaving the org dropdown on its "(Solo practice — no organization)" option. The framework constructs `ClinicianAffiliation(**payload.model_dump())`; the new row sits alongside the existing one(s).
- **Remove an ClinicianAffiliation**: `DELETE /clinicians/{id}/clinician_affiliations/{aff_id}` removes the row through the framework's generic delete handler.
