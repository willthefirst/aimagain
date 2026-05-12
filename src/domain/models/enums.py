"""Controlled-vocabulary tuples shared across model clusters.

Single source of truth for the small enums that DB columns use as
`Text` + CHECK constraints. Two clusters consume this module:

- `posts/` per-kind detail tables (`client_referral_detail`,
  `provider_availability_detail`) use `US_STATES`, the location/age/
  language/insurance vocabularies, the `DESIRED_TIME_*` axes, and the
  service/treatment-setting vocabularies.
- `Provider` and its sub-records (`provider_licensure`,
  `provider_education`, `provider_certification`) use `US_STATES`,
  `LOCATION_AVAILABILITY_OPTIONS`, and the `LICENSE_TYPES` /
  `EDUCATION_TYPES` / `CERTIFICATION_TYPES` credential vocabularies.

Lives at the parent `models/` level (not inside any cluster) precisely
because both clusters depend on it; nesting it under either would make
the other reach across cluster boundaries to import it. The module is
also a leaf — depending on nothing — so detail models can import it
without dragging in the `posts/post_kinds` registry that depends on
them in turn.

The schema layer's `Literal[*TUPLE]` types are derived from the same
tuples; the guardrail test `test_schema_literals_match_model_tuples`
(in `src/schemas/posts/test_post.py`) keeps them in lockstep.
"""

from typing import Final

US_STATES: Final[tuple[str, ...]] = (
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
)
LOCATION_AVAILABILITY_OPTIONS: Final[tuple[str, ...]] = (
    "yes",
    "no",
    "please_contact",
)
CLIENT_AGE_GROUPS: Final[tuple[str, ...]] = (
    "children_0_5",
    "children_6_10",
    "preteens_11_13",
    "adolescents_14_18",
    "young_adults_19_24",
    "adults_25_64",
    "older_adults_65_plus",
)
LANGUAGE_PREFERRED_OPTIONS: Final[tuple[str, ...]] = ("no", "yes")
INSURANCE_OPTIONS: Final[tuple[str, ...]] = (
    "in_network",
    "out_of_network",
    "in_and_out_of_network",
)

# Day × time-of-day grid for "when are you available". 21 tokens of the
# form `<day>_<slot>`. Day order is Mon→Sun (week-of-work convention from
# the form spec); slot order is morning→afternoon→evening so the
# rendered checkbox grid reads left-to-right top-to-bottom. The two
# axis tuples are exposed alongside the combined token list because the
# form-render macro iterates the grid by (day row × part column).
DESIRED_TIME_DAYS: Final[tuple[str, ...]] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DESIRED_TIME_PARTS: Final[tuple[str, ...]] = ("morning", "afternoon", "evening")
DESIRED_TIME_SLOTS: Final[tuple[str, ...]] = tuple(
    f"{day}_{part}" for day in DESIRED_TIME_DAYS for part in DESIRED_TIME_PARTS
)

# Service-line categories. The same vocabulary appears on both forms:
# optional `services` on `client_referral` (empty list allowed) and
# required-min-1 `services` on `provider_availability`. Required-ness
# differs but the value set is shared, so the tuple is single-sourced.
CLIENT_REFERRAL_SERVICES: Final[tuple[str, ...]] = (
    "evaluation",
    "medication_management",
    "psychotherapy",
    "case_management",
    "allied_health",
)

# Treatment settings categories. `provider_availability` only; required-min-1.
TREATMENT_SETTINGS: Final[tuple[str, ...]] = (
    "outpatient",
    "iop",
    "crisis_care",
    "php",
    "residential",
)


# --- Display labels for select <option>s --------------------------------
#
# Where the storage value isn't directly usable as the dropdown label
# (e.g. `children_0_5`, `in_network`), the labels live next to the tuple
# they cover. The form-render macro in
# `src/domain/templates/_shared/form_fields.html` looks up labels via these
# dicts; missing keys fail at render time. A guardrail test in
# `src/schemas/test_post.py` asserts every value in a tuple has a label.
#
# `US_STATES` deliberately has no label dict — the value (USPS
# abbreviation) is the right user-facing label.

LOCATION_AVAILABILITY_LABELS: Final[dict[str, str]] = {
    "yes": "Yes",
    "no": "No",
    "please_contact": "Please contact",
}
CLIENT_AGE_GROUP_LABELS: Final[dict[str, str]] = {
    "children_0_5": "Children 0–5",
    "children_6_10": "Children 6–10",
    "preteens_11_13": "Preteens 11–13",
    "adolescents_14_18": "Adolescents 14–18",
    "young_adults_19_24": "Young adults 19–24",
    "adults_25_64": "Adults 25–64",
    "older_adults_65_plus": "Older adults 65+",
}
LANGUAGE_PREFERRED_LABELS: Final[dict[str, str]] = {"no": "No", "yes": "Yes"}
INSURANCE_LABELS: Final[dict[str, str]] = {
    "in_network": "In-network",
    "out_of_network": "Out-of-network",
    "in_and_out_of_network": "In- and out-of-network",
}
# Per-axis labels for the desired-times grid. The form-render macro
# uses these for the row (day) and column (slot) headers; per-cell
# labels aren't needed because the checkbox value carries the meaning.
DESIRED_TIME_DAY_LABELS: Final[dict[str, str]] = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}
DESIRED_TIME_PART_LABELS: Final[dict[str, str]] = {
    "morning": "Morning",
    "afternoon": "Afternoon",
    "evening": "Evening",
}
# Combined per-token label, e.g. "Monday morning". Used wherever a
# single value is rendered standalone (read views, audit dumps shown
# in admin tooling).
DESIRED_TIME_SLOT_LABELS: Final[dict[str, str]] = {
    f"{day}_{part}": f"{DESIRED_TIME_DAY_LABELS[day]} {DESIRED_TIME_PART_LABELS[part].lower()}"
    for day in DESIRED_TIME_DAYS
    for part in DESIRED_TIME_PARTS
}
CLIENT_REFERRAL_SERVICE_LABELS: Final[dict[str, str]] = {
    "evaluation": "Evaluation",
    "medication_management": "Medication management",
    "psychotherapy": "Psychotherapy",
    "case_management": "Case management",
    "allied_health": "Allied health",
}
TREATMENT_SETTINGS_LABELS: Final[dict[str, str]] = {
    "outpatient": "Outpatient",
    "iop": "IOP",
    "crisis_care": "Crisis care",
    "php": "PHP",
    "residential": "Residential",
}

LICENSE_TYPES: Final[tuple[str, ...]] = (
    "lcsw",
    "lpc",
    "lmft",
    "lmhc",
    "lcpc",
    "psyd",
    "phd",
    "md",
    "do",
    "np",
    "pmhnp",
    "other",
)
LICENSE_TYPES_LABELS: Final[dict[str, str]] = {
    "lcsw": "Licensed Clinical Social Worker (LCSW)",
    "lpc": "Licensed Professional Counselor (LPC)",
    "lmft": "Licensed Marriage and Family Therapist (LMFT)",
    "lmhc": "Licensed Mental Health Counselor (LMHC)",
    "lcpc": "Licensed Clinical Professional Counselor (LCPC)",
    "psyd": "Doctor of Psychology (PsyD)",
    "phd": "Doctor of Philosophy (PhD)",
    "md": "Medical Doctor (MD)",
    "do": "Doctor of Osteopathic Medicine (DO)",
    "np": "Nurse Practitioner (NP)",
    "pmhnp": "Psychiatric Mental Health Nurse Practitioner (PMHNP)",
    "other": "Other",
}

EDUCATION_TYPES: Final[tuple[str, ...]] = (
    "ba_bs",
    "ma_ms",
    "msw",
    "phd",
    "psyd",
    "md",
    "do",
    "edd",
    "other",
)
EDUCATION_TYPES_LABELS: Final[dict[str, str]] = {
    "ba_bs": "Bachelor's Degree (BA/BS)",
    "ma_ms": "Master of Arts/Science (MA/MS)",
    "msw": "Master of Social Work (MSW)",
    "phd": "Doctor of Philosophy (PhD)",
    "psyd": "Doctor of Psychology (PsyD)",
    "md": "Medical Doctor (MD)",
    "do": "Doctor of Osteopathic Medicine (DO)",
    "edd": "Doctor of Education (EdD)",
    "other": "Other",
}

CERTIFICATION_TYPES: Final[tuple[str, ...]] = (
    "emdr",
    "dbt",
    "cbt",
    "gottman_1",
    "gottman_2",
    "gottman_3",
    "cpr",
    "ccatp",
    "other",
)
CERTIFICATION_TYPES_LABELS: Final[dict[str, str]] = {
    "emdr": "EMDR",
    "dbt": "DBT Certification",
    "cbt": "CBT Certification",
    "gottman_1": "Gottman Method Level 1",
    "gottman_2": "Gottman Method Level 2",
    "gottman_3": "Gottman Method Level 3",
    "cpr": "CPR Certified",
    "ccatp": "Certified Clinical Anxiety Treatment Professional (CCATP)",
    "other": "Other",
}


def check_in_tuple_sql(column: str, values: tuple[str, ...]) -> str:
    """SQL fragment for a `column IN (...)` CHECK constraint, rendered
    from a tuple. Used by per-kind detail tables so the DB-level
    vocabulary stays in lockstep with the Python tuples above. Mirrors
    the `POST_KINDS.check_sql()` pattern used by the parent `posts` table.

    Uses SQL single-quote string literals with `'` doubled per SQL
    standard. `repr()` would work for the current ASCII-only enum
    values but switches to double-quoted form when a value contains
    `'`, which SQLite parses as an identifier rather than a string —
    so it's not safe for arbitrary future values."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


def named_check_in(
    table: str, column: str, values: tuple[str, ...]
) -> "CheckConstraint":
    """`column IN (values)` CHECK named `ck_<table>_<column>`.

    Centralizes the per-model `_ck` boilerplate every entity using a
    controlled-vocabulary column was restating. Models import this
    directly instead of redeclaring a local closure over `_TABLE`.
    """
    from sqlalchemy import CheckConstraint

    return CheckConstraint(
        check_in_tuple_sql(column, values),
        name=f"ck_{table}_{column}",
    )
