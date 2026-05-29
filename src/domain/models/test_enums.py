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
    (e.REFERRAL_SERVICE_ICONS, e.ReferralService, "icons"),
    (e.GENDERS, e.Gender, "values"),
    (e.GENDER_LABELS, e.Gender, "labels"),
    (e.TREATMENT_SETTINGS, e.TreatmentSetting, "values"),
    (e.TREATMENT_SETTINGS_LABELS, e.TreatmentSetting, "labels"),
    (e.TREATMENT_SETTINGS_ICONS, e.TreatmentSetting, "icons"),
    (e.TREATMENT_MODALITIES, e.TreatmentModality, "values"),
    (e.TREATMENT_MODALITY_LABELS, e.TreatmentModality, "labels"),
    (e.INSURANCE_POSTURES, e.InsurancePosture, "values"),
    (e.INSURANCE_POSTURE_LABELS, e.InsurancePosture, "labels"),
    (e.INSURANCE_POSTURE_ICONS, e.InsurancePosture, "icons"),
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
