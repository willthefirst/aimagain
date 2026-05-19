# Clinicians cluster

The person behind a directory entry — license-holder, name on NPPES, owner of credentials.

`Clinician` was carved out of [`../providers/provider.py`](../providers/provider.py) over the four-PR `Provider → Clinician + Affiliation` split (issue #629). PR 1 (this cluster's birth) moved the `npi` column off `providers`; the credential sub-tables ([`../providers/provider_licensure.py`](../providers/provider_licensure.py), `provider_education.py`, `provider_certification.py`) moved their FK from `providers.id` to `clinicians.id` in #635 PR A — credentials are person-level (a license follows the person across affiliations), and `Clinician` owns the relationships with `cascade="all, delete-orphan"`. See [`../providers/README.md`](../providers/README.md) for the cluster the split came out of, and [`../affiliations/README.md`](../affiliations/README.md) for the practice-role side.

## Files

- `clinician.py` — `Clinician`. Holds `npi` (`Text`, nullable; `ck_clinicians_npi_format` CHECK enforces NULL or exactly 10 ASCII digits — defense-in-depth behind the Pydantic `_validate_npi`). `clinician.providers` is the back-relationship to `Provider` (1:many in the target model, 1:1 today through PR 4 — the FK on `providers.clinician_id` is non-UNIQUE so attaching a second provider is a data change, not a schema change). Also owns the credential lists: `clinician.licensures` / `.educations` / `.certifications` (`cascade="all, delete-orphan"`, `lazy="selectin"`) — `Provider.licensures` etc. are `@property` proxies delegating here so route handlers and templates keep their existing `provider.<credential>` shape. The framework's NPPES verification pipeline reads `clinician.npi` through the `Provider.clinician` join — no separate `Clinician` route surface.
- `test_clinician.py` — model-layer regression coverage (auto-create-on-Provider-init, write-routing setter, the NPI CHECK constraint).

## Why a separate cluster

A `Clinician` is *the person*; a `Provider` (today) is *the person's role at one practice*. Conflating them on one table broke the multi-affiliation clinician (private practice + Tuesdays at a community clinic + telehealth contractor across two platforms). Splitting forces credentials to live with the person — so a clinician adding a second affiliation doesn't fragment their license list — and lets per-(clinician × org) attributes vary independently. The split is in progress; until it completes, `Provider` keeps the user-facing identity and surfaces person-attributes via `provider.clinician.X` proxies.
