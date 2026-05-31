"""Controlled-vocabulary `LabeledChoice` classes; derived tuple/dict aliases.

Every labeled vocabulary is a `LabeledChoice` subclass (see `labeled_choice.py`):
the class declares value + label + optional icon per member, and the historical
`FOO` / `FOO_LABELS` / `FOO_ICONS` names are kept as derived aliases
(`Cls.values()` / `.labels()` / `.icons()`) so every downstream consumer stays
unchanged. Vocabularies whose display facts are richer than value+label+icon
(`ClientAgeGroup`, `DesiredTimeDay`) subclass with a custom `__new__` that
attaches the extra attributes; their derived dicts read those off the members.

`US_STATES` is the one plain tuple left: the value (USPS abbreviation) is its
own user-facing label, so there's nothing to single-source — one structure, no
parallel dict to drift from.
"""

from typing import Final

from src.domain.models.labeled_choice import LabeledChoice

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


class LocationAvailability(LabeledChoice):
    yes = "yes", "Yes"
    no = "no", "No"
    please_contact = "please_contact", "Please contact"


LOCATION_AVAILABILITY_OPTIONS: Final[tuple[str, ...]] = LocationAvailability.values()


# Client age cohorts. Richer than value+label+icon: each member carries a
# singular noun, a plural noun, and a numeric range. The CR card's headline
# composer in `domain/logic/posts/view.py` reads `.singular` + `.range`
# directly ("<noun> <gender> (<range>)"); `.label` is the plural+range form
# ("Children (0–5)") for PA listing rows and the filter dropdown, and
# `.label_singular` is the singular+range form. Multiple members may share an
# icon when they read the same at scan distance (children_0_5 / children_6_10).
class ClientAgeGroup(LabeledChoice):
    singular: str
    plural: str
    range: str
    label_singular: str

    children_0_5 = "children_0_5", "Child", "Children", "0–5", "baby"
    children_6_10 = "children_6_10", "Child", "Children", "6–10", "baby"
    preteens_11_13 = "preteens_11_13", "Preteen", "Preteens", "11–13", "graduation-cap"
    adolescents_14_18 = (
        "adolescents_14_18",
        "Adolescent",
        "Adolescents",
        "14–18",
        "graduation-cap",
    )
    young_adults_19_24 = (
        "young_adults_19_24",
        "Young adult",
        "Young adults",
        "19–24",
        "user",
    )
    adults_25_64 = "adults_25_64", "Adult", "Adults", "25–64", "user"
    older_adults_65_plus = (
        "older_adults_65_plus",
        "Older adult",
        "Older adults",
        "65+",
        "user-round",
    )

    def __new__(
        cls, value: str, singular: str, plural: str, range_: str, icon: str
    ) -> "ClientAgeGroup":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.singular = singular
        obj.plural = plural
        obj.range = range_
        obj.icon = icon
        obj.label = f"{plural} ({range_})"
        obj.label_singular = f"{singular} ({range_})"
        return obj


CLIENT_AGE_GROUPS: Final[tuple[str, ...]] = ClientAgeGroup.values()


# Spoken-language tokens used by the multi-valued `languages` field on
# both post kinds. Tokens are ISO-639 codes; labels are the English
# display names. Starts minimal — covers every seed example today — and
# grows as real posts demand more entries.
class Language(LabeledChoice):
    en = "en", "English"
    es = "es", "Spanish"


LANGUAGES: Final[tuple[str, ...]] = Language.values()


# Referrer's posture toward in-network matching for a `referral`.
# Paired with `insurance_carrier` (nullable, from `INSURANCE_CARRIERS`) on
# the same detail row: `network_preference` describes *strictness*,
# `insurance_carrier` describes *which carrier* (null = self-pay /
# unknown / no carrier). When `network_preference == 'no_preference'`
# the carrier value is irrelevant — the form hides the control.
class NetworkPreference(LabeledChoice):
    in_network_required = "in_network_required", "In-network required"
    in_network_preferred = "in_network_preferred", "In-network preferred"
    no_preference = "no_preference", "No preference / self-pay"


NETWORK_PREFERENCES: Final[tuple[str, ...]] = NetworkPreference.values()


# Carrier vocabulary for `Clinician.in_network_carriers` and
# `ReferralDetail.insurance_carrier`. Single-sourced so the
# referral side (one carrier per patient) and the clinician side (the
# list of carriers the practice accepts) share tokens. On the clinician
# side an empty list means "no in-network"; nullable on the referral
# side (null = self-pay / unknown / no carrier).
class InsuranceCarrier(LabeledChoice):
    aetna = "aetna", "Aetna"
    anthem_bcbs = "anthem_bcbs", "Anthem / BCBS"
    cigna = "cigna", "Cigna"
    kaiser = "kaiser", "Kaiser"
    magellan = "magellan", "Magellan"
    medicare = "medicare", "Medicare"
    medicaid = "medicaid", "Medicaid"
    optum = "optum", "Optum"
    tricare = "tricare", "Tricare"
    united_healthcare = "united_healthcare", "UnitedHealthcare"
    other = "other", "Other"


INSURANCE_CARRIERS: Final[tuple[str, ...]] = InsuranceCarrier.values()


# Day × time-of-day grid for "when are you available". 14 tokens of the
# form `<day>_<part>`. Day order is Mon→Sun (week-of-work convention from
# the form spec); part order is am→pm so the rendered grid reads
# left-to-right (am, pm columns) top-to-bottom (Mon→Sun rows). The two
# axes are their own vocabularies; the combined slot tuple/labels below
# derive from them so the grid stays single-sourced.
#
# `DesiredTimeDay` carries two labels: `.label` is the long form used in
# slot labels (e.g. "Monday AM") and `.short_label` is a compact abbreviation
# (M/T/W/Th/F/Sat/Sun) available for display contexts that need it.
class DesiredTimeDay(LabeledChoice):
    short_label: str

    monday = "monday", "Monday", "M"
    tuesday = "tuesday", "Tuesday", "T"
    wednesday = "wednesday", "Wednesday", "W"
    thursday = "thursday", "Thursday", "Th"
    friday = "friday", "Friday", "F"
    saturday = "saturday", "Saturday", "Sat"
    sunday = "sunday", "Sunday", "Sun"

    def __new__(cls, value: str, label: str, short_label: str) -> "DesiredTimeDay":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.label = label
        obj.short_label = short_label
        obj.icon = None
        return obj


class DesiredTimePart(LabeledChoice):
    am = "am", "AM"
    pm = "pm", "PM"


DESIRED_TIME_DAYS: Final[tuple[str, ...]] = DesiredTimeDay.values()
DESIRED_TIME_PARTS: Final[tuple[str, ...]] = DesiredTimePart.values()
DESIRED_TIME_SLOTS: Final[tuple[str, ...]] = tuple(
    f"{day}_{part}" for day in DESIRED_TIME_DAYS for part in DESIRED_TIME_PARTS
)


# Service-line categories. The same vocabulary appears on both forms:
# optional `services` on `referral` (empty list allowed) and
# required-min-1 `services` on `opening`. Required-ness
# differs but the value set is shared, so the tuple is single-sourced.
class ReferralService(LabeledChoice):
    evaluation = "evaluation", "Evaluation", "clipboard-list"
    medication_management = "medication_management", "Medication management", "pill"
    psychotherapy = "psychotherapy", "Psychotherapy", "message-circle"
    case_management = "case_management", "Case management", "briefcase"
    allied_health = "allied_health", "Allied health", "heart-pulse"
    group_therapy = "group_therapy", "Group therapy", "users"
    family_therapy = "family_therapy", "Family therapy", "users-round"
    couples_therapy = "couples_therapy", "Couples therapy", "heart-handshake"


REFERRAL_SERVICES: Final[tuple[str, ...]] = ReferralService.values()


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
class Gender(LabeledChoice):
    female = "female", "Female"
    male = "male", "Male"
    non_binary = "non_binary", "Non-binary"
    trans_female = "trans_female", "Trans woman"
    trans_male = "trans_male", "Trans man"
    gender_diverse = "gender_diverse", "Gender-diverse"
    prefer_not_to_say = "prefer_not_to_say", "Prefer not to say"


GENDERS: Final[tuple[str, ...]] = Gender.values()


# Treatment settings categories. `opening` only; required-min-1.
class TreatmentSetting(LabeledChoice):
    outpatient = "outpatient", "Outpatient", "house"
    iop = "iop", "IOP", "calendar-clock"
    crisis_care = "crisis_care", "Crisis care", "siren"
    php = "php", "PHP", "calendar-days"
    residential = "residential", "Residential", "hospital"
    day_program = "day_program", "Day program", "sun"


TREATMENT_SETTINGS: Final[tuple[str, ...]] = TreatmentSetting.values()


# Therapeutic modality vocabulary. Structured alternative to the legacy
# `treatment_modality` free-text column; new posts use this multi-value
# list for filterable, controlled-vocabulary modality data.
class TreatmentModality(LabeledChoice):
    psychodynamic = "psychodynamic", "Psychodynamic"
    emdr = "emdr", "EMDR"
    ifs = "ifs", "IFS"
    somatic = "somatic", "Somatic"
    cbt = "cbt", "CBT"
    dbt = "dbt", "DBT"
    act = "act", "ACT"
    motivational_interviewing = "motivational_interviewing", "Motivational interviewing"
    narrative = "narrative", "Narrative"
    gottman = "gottman", "Gottman"


TREATMENT_MODALITIES: Final[tuple[str, ...]] = TreatmentModality.values()


# --- Display labels for select <option>s --------------------------------
#
# The form-render macro in
# `src/framework/templates/_shared/form_fields.html` looks up labels via these
# `*_LABELS` dicts; missing keys fail at render time. Every dict derives from a
# `LabeledChoice` class (`Cls.labels()`, or a comprehension over the members for
# the richer vocabularies), so the label can't drift from its value.
#
# `US_STATES` deliberately has no label dict — the value (USPS
# abbreviation) is the right user-facing label.

LOCATION_AVAILABILITY_LABELS: Final[dict[str, str]] = LocationAvailability.labels()
# `CLIENT_AGE_GROUPS_BY_KEY` maps each value to its `ClientAgeGroup` member,
# whose `.singular` / `.plural` / `.range` the CR headline builder reads
# directly ("<noun> <gender> (<range>)"). The two label dicts derive the
# ready-to-render plural / singular "<noun> (<range>)" strings.
CLIENT_AGE_GROUPS_BY_KEY: Final[dict[str, ClientAgeGroup]] = {
    m.value: m for m in ClientAgeGroup
}
CLIENT_AGE_GROUP_LABELS: Final[dict[str, str]] = ClientAgeGroup.labels()
CLIENT_AGE_GROUP_LABELS_SINGULAR: Final[dict[str, str]] = {
    m.value: m.label_singular for m in ClientAgeGroup
}
LANGUAGE_LABELS: Final[dict[str, str]] = Language.labels()
NETWORK_PREFERENCE_LABELS: Final[dict[str, str]] = NetworkPreference.labels()
INSURANCE_CARRIER_LABELS: Final[dict[str, str]] = InsuranceCarrier.labels()
# Per-axis labels for the desired-times grid. The form-render macro uses these
# Days carry two labels: the long `.label` (read views, slot labels below)
# and the compact `.short_label` abbreviation (M/T/W/Th/F/Sat/Sun).
DESIRED_TIME_DAY_LABELS: Final[dict[str, str]] = DesiredTimeDay.labels()
DESIRED_TIME_DAY_SHORT_LABELS: Final[dict[str, str]] = {
    m.value: m.short_label for m in DesiredTimeDay
}
DESIRED_TIME_PART_LABELS: Final[dict[str, str]] = DesiredTimePart.labels()
# Combined per-token label, e.g. "Monday morning". Used wherever a
# single value is rendered standalone (read views, audit dumps shown
# in admin tooling).
DESIRED_TIME_SLOT_LABELS: Final[dict[str, str]] = {
    f"{day}_{part}": f"{DESIRED_TIME_DAY_LABELS[day]} {DESIRED_TIME_PART_LABELS[part]}"
    for day in DESIRED_TIME_DAYS
    for part in DESIRED_TIME_PARTS
}
REFERRAL_SERVICE_LABELS: Final[dict[str, str]] = ReferralService.labels()
TREATMENT_SETTINGS_LABELS: Final[dict[str, str]] = TreatmentSetting.labels()
TREATMENT_MODALITY_LABELS: Final[dict[str, str]] = TreatmentModality.labels()
GENDER_LABELS: Final[dict[str, str]] = Gender.labels()


# --- Unified insurance posture -----------------------------------------
#
# The two post kinds model "insurance situation" with asymmetric vocab:
#   * `referral` — `network_preference` enum
#     (`in_network_required` / `in_network_preferred` / `no_preference`)
#     paired with a nullable `insurance_carrier`.
#   * `opening` → linked `Clinician` carries the
#     `in_network_carriers` list (empty = no in-network) plus the
#     `accepts_out_of_network` / `sliding_scale` booleans.
#
# For the listing row we need *one* axis the eye can read at a glance,
# so both shapes collapse to this 4-state posture. The mapping helper
# `insurance_posture_for_post(post)` lives in
# `src/domain/logic/posts/view.py`. Adding a fifth state means: extend
# this tuple, extend the labels + icons dicts, update the helper, and
# the row macro picks it up.
class InsurancePosture(LabeledChoice):
    in_network = "in_network", "In-network", "shield-check"
    out_of_network = "out_of_network", "Out-of-network", "shield"
    self_pay = "self_pay", "Self-pay", "dollar-sign"
    please_contact = "please_contact", "Contact for insurance", "circle-help"


INSURANCE_POSTURES: Final[tuple[str, ...]] = InsurancePosture.values()
INSURANCE_POSTURE_LABELS: Final[dict[str, str]] = InsurancePosture.labels()


# Organization kind. CHECK'd at the table level — empty-tuple growth
# isn't a concern (the five tokens cover the directory's organization
# universe today; expanding it means adding one member).
class OrganizationType(LabeledChoice):
    solo_practice = "solo_practice", "Solo practice"
    group_practice = "group_practice", "Group practice"
    clinic = "clinic", "Clinic"
    health_system = "health_system", "Health system"
    other = "other", "Other"


ORGANIZATION_TYPES: Final[tuple[str, ...]] = OrganizationType.values()
ORGANIZATION_TYPES_LABELS: Final[dict[str, str]] = OrganizationType.labels()


class LicenseType(LabeledChoice):
    lcsw = "lcsw", "Licensed Clinical Social Worker (LCSW)"
    lpc = "lpc", "Licensed Professional Counselor (LPC)"
    lmft = "lmft", "Licensed Marriage and Family Therapist (LMFT)"
    lmhc = "lmhc", "Licensed Mental Health Counselor (LMHC)"
    lcpc = "lcpc", "Licensed Clinical Professional Counselor (LCPC)"
    psyd = "psyd", "Doctor of Psychology (PsyD)"
    phd = "phd", "Doctor of Philosophy (PhD)"
    md = "md", "Medical Doctor (MD)"
    do = "do", "Doctor of Osteopathic Medicine (DO)"
    np = "np", "Nurse Practitioner (NP)"
    pmhnp = "pmhnp", "Psychiatric Mental Health Nurse Practitioner (PMHNP)"
    other = "other", "Other"


LICENSE_TYPES: Final[tuple[str, ...]] = LicenseType.values()
LICENSE_TYPES_LABELS: Final[dict[str, str]] = LicenseType.labels()


class EducationType(LabeledChoice):
    ba_bs = "ba_bs", "Bachelor's Degree (BA/BS)"
    ma_ms = "ma_ms", "Master of Arts/Science (MA/MS)"
    msw = "msw", "Master of Social Work (MSW)"
    phd = "phd", "Doctor of Philosophy (PhD)"
    psyd = "psyd", "Doctor of Psychology (PsyD)"
    md = "md", "Medical Doctor (MD)"
    do = "do", "Doctor of Osteopathic Medicine (DO)"
    edd = "edd", "Doctor of Education (EdD)"
    other = "other", "Other"


EDUCATION_TYPES: Final[tuple[str, ...]] = EducationType.values()
EDUCATION_TYPES_LABELS: Final[dict[str, str]] = EducationType.labels()


class CertificationType(LabeledChoice):
    emdr = "emdr", "EMDR"
    dbt = "dbt", "DBT Certification"
    cbt = "cbt", "CBT Certification"
    gottman_1 = "gottman_1", "Gottman Method Level 1"
    gottman_2 = "gottman_2", "Gottman Method Level 2"
    gottman_3 = "gottman_3", "Gottman Method Level 3"
    cpr = "cpr", "CPR Certified"
    ccatp = "ccatp", "Certified Clinical Anxiety Treatment Professional (CCATP)"
    other = "other", "Other"


CERTIFICATION_TYPES: Final[tuple[str, ...]] = CertificationType.values()
CERTIFICATION_TYPES_LABELS: Final[dict[str, str]] = CertificationType.labels()


# Outcome of a single nightly verification attempt. `verified` —
# all checks passed; `needs_review` — a soft mismatch worth a human look
# (e.g. NPPES name similarity below threshold); `failed` — a hard
# disqualifier (NPI not in NPPES, or an OIG/LEIE match). One row per
# attempt is appended; the latest row's status is what the UI surfaces.
# Value-only (no display labels) — `.labels()` falls back to the value.
class VerificationStatus(LabeledChoice):
    verified = "verified"
    needs_review = "needs_review"
    failed = "failed"


VERIFICATION_STATUSES: Final[tuple[str, ...]] = VerificationStatus.values()


# NPPES name-match state for an NPI on a `Clinician` (Type-1) or
# `Organization` (Type-2). `none` — no NPI submitted yet; `pending` — the
# row carries an NPI and a worker has yet to resolve it; `matched` — the
# NPPES legal name (or org name + Authorized Official for Type-2) clears
# the similarity threshold; `mismatch` — final state after admin review
# rejects a soft mismatch. Per handoff §10.1, NPPES soft mismatches stay
# `pending` until an admin closes them — they never auto-flip to
# `mismatch`. The icons are Lucide names rendered by the chrome's claim
# badges.
class NpiMatchStatus(LabeledChoice):
    none = "none", "Not submitted", "circle-dashed"
    pending = "pending", "Verifying…", "loader"
    matched = "matched", "Matched", "shield-check"
    mismatch = "mismatch", "Mismatch — in review", "shield-alert"


NPI_MATCH_STATUSES: Final[tuple[str, ...]] = NpiMatchStatus.values()
NPI_MATCH_STATUS_LABELS: Final[dict[str, str]] = NpiMatchStatus.labels()


# Computed-and-stored status of a `ClinicianLicensure`. Derived on write
# from `expiration_date` and `attested_active` (see Phase 8's nightly
# expiry worker) and persisted for query-speed reasons: list views and
# the directory-listing filter both restrict on "has an active license"
# without recomputing per row.
class LicenseStatus(LabeledChoice):
    active = "active", "Active", "check"
    expired = "expired", "Expired", "x-circle"
    pending = "pending", "Pending", "loader"


LICENSE_STATUSES: Final[tuple[str, ...]] = LicenseStatus.values()
LICENSE_STATUS_LABELS: Final[dict[str, str]] = LicenseStatus.labels()


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
