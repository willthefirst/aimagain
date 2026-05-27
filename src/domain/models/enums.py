"""Controlled-vocabulary tuples (Text+CHECK columns); paired *_LABELS dicts."""

from typing import Final, NamedTuple


class AgeGroup(NamedTuple):
    """Display facts for a `CLIENT_AGE_GROUPS` token.

    One row per age token, three columns: the singular noun (for CR
    reads — one client), the plural noun (for PA reads — a cohort,
    plus the filter dropdown / form checkbox vocabulary), and the
    numeric range. The CR card's headline composer in
    `domain/logic/posts/view.py` reads `singular` + `range` directly;
    label dicts further down derive `"<noun> (<range>)"` for the read
    paths that want a single ready-to-render string.
    """

    singular: str
    plural: str
    range: str


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
# Spoken-language tokens used by the multi-valued `languages` field on
# both post kinds. Tokens are ISO-639 codes; labels are the English
# display names. The tuple starts minimal — covers every seed example
# today — and grows as real posts demand more entries.
LANGUAGES: Final[tuple[str, ...]] = ("en", "es")

# Referrer's posture toward in-network matching for a `referral`.
# Paired with `insurance_carrier` (nullable, from `INSURANCE_CARRIERS`) on
# the same detail row: `network_preference` describes *strictness*,
# `insurance_carrier` describes *which carrier* (null = self-pay /
# unknown / no carrier). When `network_preference == 'no_preference'`
# the carrier value is irrelevant — the form hides the control.
NETWORK_PREFERENCES: Final[tuple[str, ...]] = (
    "in_network_required",
    "in_network_preferred",
    "no_preference",
)

# Carrier vocabulary for `Provider.in_network_carriers` and
# `ReferralDetail.insurance_carrier`. Single-sourced so the
# referral side (one carrier per patient) and the clinician side (the
# list of carriers the practice accepts) share tokens. On the clinician
# side an empty list means "no in-network"; nullable on the referral
# side (null = self-pay / unknown / no carrier).
INSURANCE_CARRIERS: Final[tuple[str, ...]] = (
    "aetna",
    "anthem_bcbs",
    "cigna",
    "kaiser",
    "magellan",
    "medicare",
    "medicaid",
    "optum",
    "tricare",
    "united_healthcare",
    "other",
)

# Day × time-of-day grid for "when are you available". 14 tokens of the
# form `<day>_<part>`. Day order is Mon→Sun (week-of-work convention from
# the form spec); part order is am→pm so the rendered grid reads
# left-to-right (am, pm columns) top-to-bottom (Mon→Sun rows). The two
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
DESIRED_TIME_PARTS: Final[tuple[str, ...]] = ("am", "pm")
DESIRED_TIME_SLOTS: Final[tuple[str, ...]] = tuple(
    f"{day}_{part}" for day in DESIRED_TIME_DAYS for part in DESIRED_TIME_PARTS
)

# Service-line categories. The same vocabulary appears on both forms:
# optional `services` on `referral` (empty list allowed) and
# required-min-1 `services` on `opening`. Required-ness
# differs but the value set is shared, so the tuple is single-sourced.
REFERRAL_SERVICES: Final[tuple[str, ...]] = (
    "evaluation",
    "medication_management",
    "psychotherapy",
    "case_management",
    "allied_health",
    "group_therapy",
    "family_therapy",
    "couples_therapy",
)

# Gender identity vocabulary. Single-axis enum that folds trans/cis into
# the value (`female` / `trans_female`) rather than splitting into two
# fields — for the listing row the reader wants one labeled chunk
# ("Gender: Trans woman"), not a parenthesized modifier. `gender_diverse`
# is the umbrella token for genderqueer / agender / two-spirit / etc.;
# `prefer_not_to_say` is the privacy-respecting opt-out.
#
# Used as a scalar on `referral` (`gender`: the client's identity)
# and as a multi-value list on `opening` (`genders`: the
# practice serves these).
GENDERS: Final[tuple[str, ...]] = (
    "female",
    "male",
    "non_binary",
    "trans_female",
    "trans_male",
    "gender_diverse",
    "prefer_not_to_say",
)

# Treatment settings categories. `opening` only; required-min-1.
TREATMENT_SETTINGS: Final[tuple[str, ...]] = (
    "outpatient",
    "iop",
    "crisis_care",
    "php",
    "residential",
    "day_program",
)


# --- Display labels for select <option>s --------------------------------
#
# Where the storage value isn't directly usable as the dropdown label
# (e.g. `children_0_5`, `in_network`), the labels live next to the tuple
# they cover. The form-render macro in
# `src/framework/templates/_shared/form_fields.html` looks up labels via these
# dicts; missing keys fail at render time. A guardrail test in
# `src/domain/logic/posts/test_schema.py` asserts every value in a tuple has a label.
#
# `US_STATES` deliberately has no label dict — the value (USPS
# abbreviation) is the right user-facing label.

LOCATION_AVAILABILITY_LABELS: Final[dict[str, str]] = {
    "yes": "Yes",
    "no": "No",
    "please_contact": "Please contact",
}
# One AgeGroup row per `CLIENT_AGE_GROUPS` token, carrying every
# display fact (singular noun, plural noun, numeric range). All other
# dicts derive from this — adding a value means editing one row, not
# six. The `*_LABELS` / `*_LABELS_SINGULAR` derivations are kept so
# call sites that want a single ready-to-render string don't have to
# format. Direct attribute access on the `AgeGroup` (e.g.
# `CLIENT_AGE_GROUPS_BY_KEY[k].singular`) is the right shape for the
# CR headline builder, which composes "<noun> <gender> (<range>)".
CLIENT_AGE_GROUPS_BY_KEY: Final[dict[str, AgeGroup]] = {
    "children_0_5": AgeGroup("Child", "Children", "0–5"),
    "children_6_10": AgeGroup("Child", "Children", "6–10"),
    "preteens_11_13": AgeGroup("Preteen", "Preteens", "11–13"),
    "adolescents_14_18": AgeGroup("Adolescent", "Adolescents", "14–18"),
    "young_adults_19_24": AgeGroup("Young adult", "Young adults", "19–24"),
    "adults_25_64": AgeGroup("Adult", "Adults", "25–64"),
    "older_adults_65_plus": AgeGroup("Older adult", "Older adults", "65+"),
}
CLIENT_AGE_GROUP_LABELS: Final[dict[str, str]] = {
    k: f"{g.plural} ({g.range})" for k, g in CLIENT_AGE_GROUPS_BY_KEY.items()
}
CLIENT_AGE_GROUP_LABELS_SINGULAR: Final[dict[str, str]] = {
    k: f"{g.singular} ({g.range})" for k, g in CLIENT_AGE_GROUPS_BY_KEY.items()
}
LANGUAGE_LABELS: Final[dict[str, str]] = {"en": "English", "es": "Spanish"}
NETWORK_PREFERENCE_LABELS: Final[dict[str, str]] = {
    "in_network_required": "In-network required",
    "in_network_preferred": "In-network preferred",
    "no_preference": "No preference / self-pay",
}
INSURANCE_CARRIER_LABELS: Final[dict[str, str]] = {
    "aetna": "Aetna",
    "anthem_bcbs": "Anthem / BCBS",
    "cigna": "Cigna",
    "kaiser": "Kaiser",
    "magellan": "Magellan",
    "medicare": "Medicare",
    "medicaid": "Medicaid",
    "optum": "Optum",
    "tricare": "Tricare",
    "united_healthcare": "UnitedHealthcare",
    "other": "Other",
}
# Per-axis labels for the desired-times grid. The form-render macro
# uses these for the row (day) and column (slot) headers; per-cell
# labels aren't needed because the checkbox value carries the meaning.
# Two label maps for days. `DESIRED_TIME_DAY_LABELS` is the long
# form used in read-views (detail pages, audit dumps via
# `DESIRED_TIME_SLOT_LABELS`). `DESIRED_TIME_DAY_SHORT_LABELS` is the
# row-header form used in the compact `time_grid_field` checkbox grid
# (M/T/W/Th/F/Sat/Sun).
DESIRED_TIME_DAY_LABELS: Final[dict[str, str]] = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}
DESIRED_TIME_DAY_SHORT_LABELS: Final[dict[str, str]] = {
    "monday": "M",
    "tuesday": "T",
    "wednesday": "W",
    "thursday": "Th",
    "friday": "F",
    "saturday": "Sat",
    "sunday": "Sun",
}
DESIRED_TIME_PART_LABELS: Final[dict[str, str]] = {
    "am": "AM",
    "pm": "PM",
}
# Combined per-token label, e.g. "Monday morning". Used wherever a
# single value is rendered standalone (read views, audit dumps shown
# in admin tooling).
DESIRED_TIME_SLOT_LABELS: Final[dict[str, str]] = {
    f"{day}_{part}": f"{DESIRED_TIME_DAY_LABELS[day]} {DESIRED_TIME_PART_LABELS[part]}"
    for day in DESIRED_TIME_DAYS
    for part in DESIRED_TIME_PARTS
}
REFERRAL_SERVICE_LABELS: Final[dict[str, str]] = {
    "evaluation": "Evaluation",
    "medication_management": "Medication management",
    "psychotherapy": "Psychotherapy",
    "case_management": "Case management",
    "allied_health": "Allied health",
    "group_therapy": "Group therapy",
    "family_therapy": "Family therapy",
    "couples_therapy": "Couples therapy",
}
TREATMENT_SETTINGS_LABELS: Final[dict[str, str]] = {
    "outpatient": "Outpatient",
    "iop": "IOP",
    "crisis_care": "Crisis care",
    "php": "PHP",
    "residential": "Residential",
    "day_program": "Day program",
}
GENDER_LABELS: Final[dict[str, str]] = {
    "female": "Female",
    "male": "Male",
    "non_binary": "Non-binary",
    "trans_female": "Trans woman",
    "trans_male": "Trans man",
    "gender_diverse": "Gender-diverse",
    "prefer_not_to_say": "Prefer not to say",
}

# --- Unified insurance posture -----------------------------------------
#
# The two post kinds model "insurance situation" with asymmetric vocab:
#   * `referral` — `network_preference` enum
#     (`in_network_required` / `in_network_preferred` / `no_preference`)
#     paired with a nullable `insurance_carrier`.
#   * `opening` → linked `Provider` carries the
#     `in_network_carriers` list (empty = no in-network) plus the
#     `accepts_out_of_network` / `sliding_scale` booleans.
#
# For the listing row we need *one* axis the eye can read at a glance,
# so both shapes collapse to this 4-state posture. The mapping helper
# `insurance_posture_for_post(post)` lives in
# `src/domain/logic/posts/view.py`. Adding a fifth state means: extend
# this tuple, extend the labels + icons dicts, update the helper, and
# the row macro picks it up.
INSURANCE_POSTURES: Final[tuple[str, ...]] = (
    "in_network",
    "out_of_network",
    "self_pay",
    "please_contact",
)
INSURANCE_POSTURE_LABELS: Final[dict[str, str]] = {
    "in_network": "In-network",
    "out_of_network": "Out-of-network",
    "self_pay": "Self-pay",
    "please_contact": "Contact for insurance",
}


# --- Lucide icon names ------------------------------------------------
#
# Icon names are keyed by the same enum storage value as the matching
# `*_LABELS` dict — renaming a *label* leaves these untouched; adding
# or renaming an *enum value* touches the tuple, the labels dict, and
# the icons dict in lockstep (the `test_icons_cover_their_tuples`
# guardrail in `src/domain/logic/posts/test_schema.py` fails the build
# if you forget one). Values are Lucide icon names (`lucide-static`
# font CSS exposes them as `<i class="icon-<name>">`); the row macro
# in `src/domain/templates/posts/_item.html` emits the `<i>` tag.
#
# Multiple enum values may share an icon when the visual signal at
# scan distance is the same — e.g. children_0_5 and children_6_10 both
# read as "kid" in the row. The detail page still distinguishes via
# `CLIENT_AGE_GROUP_LABELS`.
CLIENT_AGE_GROUP_ICONS: Final[dict[str, str]] = {
    "children_0_5": "baby",
    "children_6_10": "baby",
    "preteens_11_13": "graduation-cap",
    "adolescents_14_18": "graduation-cap",
    "young_adults_19_24": "user",
    "adults_25_64": "user",
    "older_adults_65_plus": "user-round",
}
REFERRAL_SERVICE_ICONS: Final[dict[str, str]] = {
    "evaluation": "clipboard-list",
    "medication_management": "pill",
    "psychotherapy": "message-circle",
    "case_management": "briefcase",
    "allied_health": "heart-pulse",
    "group_therapy": "users",
    "family_therapy": "users-round",
    "couples_therapy": "heart-handshake",
}
TREATMENT_SETTINGS_ICONS: Final[dict[str, str]] = {
    "outpatient": "house",
    "iop": "calendar-clock",
    "php": "calendar-days",
    "crisis_care": "siren",
    "residential": "hospital",
    "day_program": "sun",
}
INSURANCE_POSTURE_ICONS: Final[dict[str, str]] = {
    "in_network": "shield-check",
    "out_of_network": "shield",
    "self_pay": "dollar-sign",
    "please_contact": "circle-help",
}

# Organization kind. CHECK'd at the table level — empty-tuple growth
# isn't a concern (the five tokens cover the directory's organization
# universe today; expanding it means editing one tuple).
ORGANIZATION_TYPES: Final[tuple[str, ...]] = (
    "solo_practice",
    "group_practice",
    "clinic",
    "health_system",
    "other",
)
ORGANIZATION_TYPES_LABELS: Final[dict[str, str]] = {
    "solo_practice": "Solo practice",
    "group_practice": "Group practice",
    "clinic": "Clinic",
    "health_system": "Health system",
    "other": "Other",
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

# Outcome of a single nightly verification attempt. `verified` —
# all checks passed; `needs_review` — a soft mismatch worth a human look
# (e.g. NPPES name similarity below threshold); `failed` — a hard
# disqualifier (NPI not in NPPES, or an OIG/LEIE match). One row per
# attempt is appended; the latest row's status is what the UI surfaces.
VERIFICATION_STATUSES: Final[tuple[str, ...]] = (
    "verified",
    "needs_review",
    "failed",
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
