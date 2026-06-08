"""Pins the controlled-vocabulary storage values + their derived aliases.

The `LabeledChoice` migration must be a no-op for storage and the wire: the
exact value set of each migrated vocabulary is frozen here, and the historical
`FOO` / `FOO_LABELS` / `FOO_ICONS` aliases must stay identical to what the class
derives. A typo in a member value (which would silently widen/narrow a DB CHECK
universe and break persisted rows) fails here, offline.
"""

import pytest

from src.domain.models import enums as e

# Frozen expected storage values per migrated vocabulary. Editing a value here
# is a schema change — it must come with an Alembic migration.
MIGRATED_VALUES = {
    e.LocationAvailability: ("yes", "no", "please_contact"),
    e.Language: ("en", "es"),
    e.NetworkPreference: (
        "in_network_required",
        "in_network_preferred",
        "no_preference",
    ),
    e.InsuranceCarrier: (
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
    ),
    e.ReferralService: (
        "evaluation",
        "medication_management",
        "psychotherapy",
        "case_management",
        "allied_health",
        "group_therapy",
        "family_therapy",
        "couples_therapy",
    ),
    e.Gender: (
        "female",
        "male",
        "non_binary",
        "trans_female",
        "trans_male",
        "gender_diverse",
        "prefer_not_to_say",
    ),
    e.TreatmentSetting: (
        "outpatient",
        "iop",
        "crisis_care",
        "php",
        "residential",
        "day_program",
    ),
    e.TreatmentModality: (
        "psychodynamic",
        "emdr",
        "ifs",
        "somatic",
        "cbt",
        "dbt",
        "act",
        "motivational_interviewing",
        "narrative",
        "gottman",
    ),
    e.InsurancePosture: (
        "in_network",
        "out_of_network",
        "self_pay",
        "please_contact",
    ),
    e.LicenseType: (
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
    ),
    e.EducationType: (
        "ba_bs",
        "ma_ms",
        "msw",
        "phd",
        "psyd",
        "md",
        "do",
        "edd",
        "other",
    ),
    e.CertificationType: (
        "emdr",
        "dbt",
        "cbt",
        "gottman_1",
        "gottman_2",
        "gottman_3",
        "cpr",
        "ccatp",
        "other",
    ),
    # Value-only vocabulary — labels fall back to the storage value.
    e.VerificationStatus: ("verified", "needs_review", "failed"),
    e.NpiMatchStatus: ("none", "pending", "matched", "mismatch"),
    e.LicenseStatus: ("active", "expired", "pending"),
    e.VerificationEventType: (
        "npi_submitted",
        "npi_resolved",
        "license_attested",
        "license_expired",
        "authority_proven",
        "authority_revoked",
        "role_set",
        "admin_verify",
        "admin_suspend",
        "email_confirmed",
    ),
    e.VerificationSubjectType: ("clinician", "organization"),
    e.OrgRepresentationRole: ("coordinator", "admin", "owner"),
    e.AuthorityMethod: (
        "authorized_official",
        "domain_email",
        "rep_approval",
        "admin_review",
    ),
    e.AuthorityStatus: ("pending", "verified", "rejected"),
    e.ClientAgeGroup: (
        "children_0_5",
        "children_6_10",
        "preteens_11_13",
        "adolescents_14_18",
        "young_adults_19_24",
        "adults_25_64",
        "older_adults_65_plus",
    ),
    e.DesiredTimeDay: (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ),
    e.DesiredTimePart: ("am", "pm"),
}

# Aliases that must equal the class derivation. (alias, class, kind).
ALIAS_BINDINGS = [
    (e.LOCATION_AVAILABILITY_OPTIONS, e.LocationAvailability, "values"),
    (e.LOCATION_AVAILABILITY_LABELS, e.LocationAvailability, "labels"),
    (e.LANGUAGES, e.Language, "values"),
    (e.LANGUAGE_LABELS, e.Language, "labels"),
    (e.NETWORK_PREFERENCES, e.NetworkPreference, "values"),
    (e.NETWORK_PREFERENCE_LABELS, e.NetworkPreference, "labels"),
    (e.INSURANCE_CARRIERS, e.InsuranceCarrier, "values"),
    (e.INSURANCE_CARRIER_LABELS, e.InsuranceCarrier, "labels"),
    (e.REFERRAL_SERVICES, e.ReferralService, "values"),
    (e.REFERRAL_SERVICE_LABELS, e.ReferralService, "labels"),
    (e.GENDERS, e.Gender, "values"),
    (e.GENDER_LABELS, e.Gender, "labels"),
    (e.TREATMENT_SETTINGS, e.TreatmentSetting, "values"),
    (e.TREATMENT_SETTINGS_LABELS, e.TreatmentSetting, "labels"),
    (e.TREATMENT_MODALITIES, e.TreatmentModality, "values"),
    (e.TREATMENT_MODALITY_LABELS, e.TreatmentModality, "labels"),
    (e.INSURANCE_POSTURES, e.InsurancePosture, "values"),
    (e.INSURANCE_POSTURE_LABELS, e.InsurancePosture, "labels"),
    (e.LICENSE_TYPES, e.LicenseType, "values"),
    (e.LICENSE_TYPES_LABELS, e.LicenseType, "labels"),
    (e.EDUCATION_TYPES, e.EducationType, "values"),
    (e.EDUCATION_TYPES_LABELS, e.EducationType, "labels"),
    (e.CERTIFICATION_TYPES, e.CertificationType, "values"),
    (e.CERTIFICATION_TYPES_LABELS, e.CertificationType, "labels"),
    # Value-only — only a values alias exists (no `*_LABELS` dict).
    (e.VERIFICATION_STATUSES, e.VerificationStatus, "values"),
    (e.NPI_MATCH_STATUSES, e.NpiMatchStatus, "values"),
    (e.NPI_MATCH_STATUS_LABELS, e.NpiMatchStatus, "labels"),
    (e.LICENSE_STATUSES, e.LicenseStatus, "values"),
    (e.LICENSE_STATUS_LABELS, e.LicenseStatus, "labels"),
    (e.VERIFICATION_EVENT_TYPES, e.VerificationEventType, "values"),
    (e.VERIFICATION_SUBJECT_TYPES, e.VerificationSubjectType, "values"),
    (e.ORG_REPRESENTATION_ROLES, e.OrgRepresentationRole, "values"),
    (e.ORG_REPRESENTATION_ROLE_LABELS, e.OrgRepresentationRole, "labels"),
    (e.AUTHORITY_METHODS, e.AuthorityMethod, "values"),
    (e.AUTHORITY_METHOD_LABELS, e.AuthorityMethod, "labels"),
    (e.AUTHORITY_STATUSES, e.AuthorityStatus, "values"),
    (e.AUTHORITY_STATUS_LABELS, e.AuthorityStatus, "labels"),
    # Multi-attribute vocabularies — the standard-kind aliases still bind to
    # `.values()` / `.labels()` / `.icons()`; the extra-attribute derivations
    # (`*_BY_KEY`, `*_SINGULAR`, `*_SHORT_LABELS`, composite slots) are pinned
    # in dedicated tests below.
    (e.CLIENT_AGE_GROUPS, e.ClientAgeGroup, "values"),
    (e.CLIENT_AGE_GROUP_LABELS, e.ClientAgeGroup, "labels"),
    (e.DESIRED_TIME_DAYS, e.DesiredTimeDay, "values"),
    (e.DESIRED_TIME_DAY_LABELS, e.DesiredTimeDay, "labels"),
    (e.DESIRED_TIME_PARTS, e.DesiredTimePart, "values"),
    (e.DESIRED_TIME_PART_LABELS, e.DesiredTimePart, "labels"),
]


@pytest.mark.parametrize("cls,expected", MIGRATED_VALUES.items())
def test_migrated_vocabulary_values_are_frozen(cls, expected):
    assert cls.values() == expected


@pytest.mark.parametrize("cls,expected", MIGRATED_VALUES.items())
def test_labels_and_icons_cover_every_value(cls, expected):
    assert set(cls.labels()) == set(expected)
    assert set(cls.icons()) == set(expected)


@pytest.mark.parametrize("alias,cls,kind", ALIAS_BINDINGS)
def test_alias_equals_class_derivation(alias, cls, kind):
    assert alias == getattr(cls, kind)()


def test_icon_bearing_vocabularies_have_an_icon_per_member():
    for cls in (e.ReferralService, e.TreatmentSetting, e.InsurancePosture):
        assert all(icon is not None for icon in cls.icons().values())


# --- Multi-attribute vocabularies ---------------------------------------
# `ClientAgeGroup` / `DesiredTimeDay` carry display facts beyond
# value+label+icon. The derivations below aren't `.values()`/`.labels()`/
# `.icons()`, so they're pinned here rather than in `ALIAS_BINDINGS`.


def test_client_age_group_carries_singular_plural_range():
    g = e.ClientAgeGroup.children_0_5
    assert (g.singular, g.plural, g.range) == ("Child", "Children", "0–5")
    # `.label` is the plural+range form; `.label_singular` the singular+range.
    assert g.label == "Children (0–5)"
    assert g.label_singular == "Child (0–5)"


def test_client_age_group_by_key_returns_members_with_attrs():
    assert set(e.CLIENT_AGE_GROUPS_BY_KEY) == set(e.CLIENT_AGE_GROUPS)
    m = e.CLIENT_AGE_GROUPS_BY_KEY["older_adults_65_plus"]
    assert m is e.ClientAgeGroup.older_adults_65_plus
    assert (m.singular, m.range) == ("Older adult", "65+")


def test_client_age_group_singular_labels_derive_from_members():
    assert e.CLIENT_AGE_GROUP_LABELS_SINGULAR == {
        m.value: m.label_singular for m in e.ClientAgeGroup
    }


def test_desired_time_day_short_labels_derive_from_members():
    assert e.DESIRED_TIME_DAY_SHORT_LABELS == {
        m.value: m.short_label for m in e.DesiredTimeDay
    }
    assert e.DesiredTimeDay.thursday.short_label == "Th"


def test_desired_time_slots_are_the_day_part_cross_product():
    assert e.DESIRED_TIME_SLOTS == tuple(
        f"{day}_{part}" for day in e.DESIRED_TIME_DAYS for part in e.DESIRED_TIME_PARTS
    )
    assert e.DESIRED_TIME_SLOT_LABELS["monday_am"] == "Monday AM"
    assert set(e.DESIRED_TIME_SLOT_LABELS) == set(e.DESIRED_TIME_SLOTS)
