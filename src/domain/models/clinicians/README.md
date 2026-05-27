# Clinicians cluster

The person behind a directory entry — license-holder, name on NPPES, owner of credentials.

`Clinician` was carved out of `providers` over the `Provider → Clinician + Affiliation` split (issues #629, #635, #642). The credential sub-tables (`provider_licensure.py`, `provider_education.py`, `provider_certification.py` — class names preserved) have their FK on `clinicians.id`; credentials are person-level (a license follows the person across affiliations). `Clinician` owns the credential relationships with `cascade="all, delete-orphan"`. See [`../affiliations/README.md`](../affiliations/README.md) for the practice-role side.

## Model-vs-UI vocabulary

This `Clinician` class is the **directory entry**: the row that `/clinicians/...` URLs, templates, and audit logs (`resource_type="clinician"`) refer to. It owns NPI, credentials, and affiliations. The legacy `Provider` class that previously held the directory role has been dropped; `Clinician` is now the single model for both the person and the directory entry.

## Files

- `clinician.py` — `Clinician`. Holds `npi` (`Text`, nullable; `ck_clinicians_npi_format` CHECK enforces NULL or exactly 10 ASCII digits — defense-in-depth behind the Pydantic `_validate_npi`). Owns the credential lists: `clinician.licensures` / `.educations` / `.certifications` (`cascade="all, delete-orphan"`, `lazy="selectin"`). Also owns `clinician.affiliations` (the per-(clinician × org) role rows). The NPPES verification pipeline reads `clinician.npi` directly.
- `test_clinician.py` — model-layer regression coverage (NPI CHECK constraint, credential relationships).

## Why a separate cluster

A `Clinician` is *the person*; an `Affiliation` is *the person's role at one practice*. Separating them lets credentials live with the person (so adding a second affiliation doesn't fragment a license list) and lets per-(clinician × org) attributes vary independently across affiliations.
