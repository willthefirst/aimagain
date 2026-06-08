# Organizations cluster

First-class directory entity for any practice (clinic, group practice, health system, solo-practice shell). PR 2 of the Org/Program roadmap (#520) wired Clinician to Organization via an `org_id` FK on the former `providers` table; in #635 PR B that FK moved to `affiliations.org_id` (along with the rest of the per-role columns), so the Org→Clinician path now navigates `affiliations` rather than a back-relationship on this table.

The parent layer's conventions (BaseModel inheritance, FK CASCADE, migration workflow) live in [`../README.md`](../README.md); this README covers what's specific to organizations.

## Files

- `organization.py` — `Organization`. Flat directory entity (no parent/root hierarchy). Tied to a `User` via non-unique `owner_id` FK + CASCADE (one user may own many orgs). Carries an optional Type-2 `npi` (NPPES 10-digit format CHECK) plus the Claim-B verification cache (`npi_match_status`, `org_verified`, `verified_at`, `authorized_official_name`). The Org→Clinician direction is reached through `ClinicianAffiliation.org_id` (RESTRICT — deleting an Org with attached Affiliations fails loudly); there is no `Organization.clinicians` back-relationship. The `Organization.programs` collection (RESTRICT) remains for the Program child.

## Why this cluster, not flat siblings

`organizations/` matches the per-entity cluster grammar in [`../README.md`](../README.md) — every entity with at least one model file gets its own directory. The Program entity (PR 4 of the Org/Program roadmap, #537) is owned by Organization but lives in its own [`../programs/`](../programs/) cluster — same parent-cluster grammar applied recursively, not nested inside `organizations/`.
