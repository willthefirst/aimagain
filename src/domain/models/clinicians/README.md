# Clinicians cluster

The person behind a directory entry — license-holder, name on NPPES, owner of credentials.

`Clinician` was carved out of `providers` over the `Provider → Clinician + ClinicianAffiliation` split (issues #629, #635, #642). The credential sub-tables (`clinician_licensure.py`, `clinician_education.py`, `clinician_certification.py` — Python classes `ClinicianLicensure`, `ClinicianEducation`, `ClinicianCertification`) have their FK on `clinicians.id`; credentials are person-level (a license follows the person across affiliations). `Clinician` owns the credential relationships with `cascade="all, delete-orphan"`. See [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md) for the practice-role side.

## Model-vs-UI vocabulary

This `Clinician` class is the **directory entry**: the row that `/clinicians/...` URLs, templates, and audit logs (`resource_type="clinician"`) refer to. It owns NPI, credentials, and affiliations.

## Files

- `clinician.py` — `Clinician`. Holds `npi` (`Text`, nullable; `ck_clinicians_npi_format` CHECK enforces NULL or exactly 10 ASCII digits — defense-in-depth behind the Pydantic `_validate_npi`). Owns the credential lists: `clinician.licensures` / `.educations` / `.certifications` (`cascade="all, delete-orphan"`, `lazy="selectin"`). Also owns `clinician.clinician_affiliations` (the per-(clinician × org) role rows). The NPPES verification pipeline reads `clinician.npi` directly. The `affirming_identities` JSON column carries the clinician's self-claimed affirming-identity vocabulary (`AFFIRMING_IDENTITIES` in [`../enums.py`](../enums.py)) — person-level because the claim moves with the person across affiliations, the same way credentials do; vocabulary is enforced on the wire by Pydantic, not via a SQL CHECK on JSON array members. The `clinical_niches` JSON column carries free-form niche tags ("DGBI", "ADHD in women", "complex trauma") — also person-level, symmetric to `ReferralDetail.clinical_niches`. Deliberately **not** an enum (#1358 PR-c): the niche vocabulary is too open-ended on day one; heavily-used tags graduate to `Literal[*ENUM]` once usage stabilizes. The wire validator `clean_free_form_tags` strips, drops empties, and deduplicates each tag — no SQL CHECK against JSON array members. The `languages` JSON column carries the languages the clinician can deliver care in (#1358 PR-f sub-1) — person-level, defaulting to `["en"]`; same vocabulary-on-the-wire pattern as `affirming_identities`. As of sub-PR 2 the opening-side view layer reads this column as the source of truth for an opening's `languages` (with detail-row fallback during the dual-write window), and `PostRepository` mirrors a fresh / patched `OpeningDetail.languages` back onto this row. The matching steady-state practice profile (services / modalities / age-groups served / etc.) lives on `ClinicianAffiliation` — see [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md#steady-state-profile-1358-pr-f-in-progress).
- `clinician_licensure.py` — `ClinicianLicensure`. One row per professional license. FK `clinician_id` → `clinicians.id` (CASCADE). `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `clinician_education.py` — `ClinicianEducation`. One row per educational credential. FK `clinician_id` → `clinicians.id` (CASCADE). `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` stores `"YYYY-MM"` text.
- `clinician_certification.py` — `ClinicianCertification`. One row per professional certification. FK `clinician_id` → `clinicians.id` (CASCADE). `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_clinician.py` — model-layer regression coverage (NPI CHECK constraint, credential relationships).
- `test_clinician_models.py` — DB-layer coverage of the credential cluster.

## Adding a new credential type

1. Add `clinician_<credential>.py` here, following the shape of `clinician_certification.py`: class name `Clinician<Credential>`, extends `BaseModel`, `clinician_id` FK to `clinicians` with CASCADE, enum columns checking against `../enums.py` tuples.
2. Add a `relationship("Clinician<Credential>", cascade="all, delete-orphan", lazy="selectin")` on `Clinician`.
3. Re-export from [`../../__init__.py`](../../__init__.py).
4. Add vocabulary tuple + labels dict to `../enums.py`.
5. Generate an Alembic migration.

## Why a separate cluster

A `Clinician` is *the person*; an `ClinicianAffiliation` is *the person's role at one practice*. Separating them lets credentials live with the person (so adding a second affiliation doesn't fragment a license list) and lets per-(clinician × org) attributes vary independently across affiliations.

## Per-affiliation proxy setters require a primary affiliation

`Clinician` exposes proxy `@property`/setter pairs for the per-affiliation columns (`org_id`, `location_city`/`_state`/`_zip`, `in_person_sessions`, `virtual_sessions`, `accepts_out_of_network`, `in_network_carriers`, `sliding_scale`, `cost` — the `_PER_ROLE_ATTRS` tuple). They proxy reads from / writes to `primary_clinician_affiliation` (`clinician_affiliations[0]`). When no affiliation exists the **setters raise `ValueError`** rather than silently dropping the write — this catches the prod regression where an unaffiliated clinician's edit form returned 200 but persisted nothing. The readers still return `None` for backwards compatibility with templates that may render an unaffiliated row.

In practice, every clinician has ≥1 affiliation: `after_create_clinician_verification` ([`../../logic/clinicians/handlers.py`](../../logic/clinicians/handlers.py)) auto-creates a stub `ClinicianAffiliation` (`org_id` NULL) for a newly-verified solo clinician, and the backfill migration `9501786659b3` covers pre-existing rows. So the proxy raise is the **belt** behind that **suspenders** invariant — anything that bypasses the verification path (admin axes, direct constructors in tests) and tries to write through the proxy still fails loudly. See [`../clinician_affiliations/README.md`](../clinician_affiliations/README.md) for the affiliation-as-posture-container story and the solo `org_id IS NULL` case.
