# Provider credential models

This subdirectory holds the three professional-credential sub-record types that belong to a `Clinician`. The `Provider` model itself has been merged into `Clinician` — this cluster survives to house the credential tables whose class names and DB table names use the "provider" vocabulary (matching the healthcare concept of a "National Provider Identifier").

The parent layer's conventions (BaseModel inheritance, FK-relationship coverage, migration workflow) live in [`../README.md`](../README.md).

## Files

- `provider_licensure.py` — `ProviderLicensure`. One row per professional license held by a clinician. FK `clinician_id` → `clinicians.id` (CASCADE). `license_type` CHECKs against `LICENSE_TYPES`; `issuing_state` CHECKs against `US_STATES`.
- `provider_education.py` — `ProviderEducation`. One row per educational credential. FK `clinician_id` → `clinicians.id` (CASCADE). `education_type` CHECKs against `EDUCATION_TYPES`. `month_completed` stores `"YYYY-MM"` text.
- `provider_certification.py` — `ProviderCertification`. One row per professional certification. FK `clinician_id` → `clinicians.id` (CASCADE). `certification_type` CHECKs against `CERTIFICATION_TYPES`.
- `test_provider_models.py` — DB-layer coverage of the credential cluster.
- `test_provider_enums.py` — asserts every credential vocabulary value (`LICENSE_TYPES`, `EDUCATION_TYPES`, `CERTIFICATION_TYPES`) has a matching `*_LABELS` entry.

## Adding a new credential type

1. Add `provider_<credential>.py` here, following the shape of `provider_certification.py`: extends `BaseModel`, `clinician_id` FK to `clinicians` with CASCADE, enum columns checking against `../enums.py` tuples.
2. Add a `relationship("Provider<Credential>", cascade="all, delete-orphan", lazy="selectin")` on `Clinician`.
3. Re-export from [`../__init__.py`](../__init__.py).
4. Add vocabulary tuple + labels dict to `../enums.py`.
5. Generate an Alembic migration.

The full cross-layer recipe lives in [`src/README.md`](../../../README.md#adding-a-new-domain-entity).
