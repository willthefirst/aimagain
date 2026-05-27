# Clinicians cluster

The person behind a directory entry — license-holder, name on NPPES, owner of credentials.

`Clinician` was carved out of `providers` over the `Provider → Clinician + Affiliation` split (issues #629, #635, #642). The credential sub-tables (`clinician_licensure.py`, `clinician_education.py`, `clinician_certification.py` — Python classes `ClinicianLicensure`, `ClinicianEducation`, `ClinicianCertification`) have their FK on `clinicians.id`; credentials are person-level (a license follows the person across affiliations). `Clinician` owns the credential relationships with `cascade="all, delete-orphan"`. See [`../affiliations/README.md`](../affiliations/README.md) for the practice-role side.

## Model-vs-UI vocabulary

This `Clinician` class is the **directory entry**: the row that `/clinicians/...` URLs, templates, and audit logs (`resource_type="clinician"`) refer to. It owns NPI, credentials, and affiliations.

## Files

- `clinician.py` — `Clinician`. Holds `npi` (`Text`, nullable; `ck_clinicians_npi_format` CHECK enforces NULL or exactly 10 ASCII digits — defense-in-depth behind the Pydantic `_validate_npi`). Owns the credential lists: `clinician.licensures` / `.educations` / `.certifications` (`cascade="all, delete-orphan"`, `lazy="selectin"`). Also owns `clinician.affiliations` (the per-(clinician × org) role rows). The NPPES verification pipeline reads `clinician.npi` directly.
- `clinician_licensure.py` — `ClinicianLicensure`. One row per professional license. FK `clinician_id` → `clinicians.id` (CASCADE). `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `clinician_education.py` — `ClinicianEducation`. One row per educational credential. FK `clinician_id` → `clinicians.id` (CASCADE). `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` stores `"YYYY-MM"` text.
- `clinician_certification.py` — `ClinicianCertification`. One row per professional certification. FK `clinician_id` → `clinicians.id` (CASCADE). `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_clinician.py` — model-layer regression coverage (NPI CHECK constraint, credential relationships).
- `test_clinician_models.py` — DB-layer coverage of the credential cluster.
- `test_clinician_enums.py` — asserts every credential vocabulary value (`LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES`) has a matching `*_LABELS` entry.

## Adding a new credential type

1. Add `clinician_<credential>.py` here, following the shape of `clinician_certification.py`: class name `Clinician<Credential>`, extends `BaseModel`, `clinician_id` FK to `clinicians` with CASCADE, enum columns checking against `../enums.py` tuples.
2. Add a `relationship("Clinician<Credential>", cascade="all, delete-orphan", lazy="selectin")` on `Clinician`.
3. Re-export from [`../../__init__.py`](../../__init__.py).
4. Add vocabulary tuple + labels dict to `../enums.py`.
5. Generate an Alembic migration.

## Why a separate cluster

A `Clinician` is *the person*; an `Affiliation` is *the person's role at one practice*. Separating them lets credentials live with the person (so adding a second affiliation doesn't fragment a license list) and lets per-(clinician × org) attributes vary independently across affiliations.
