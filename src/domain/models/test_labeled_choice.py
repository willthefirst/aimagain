"""Pins `LabeledChoice` behavior: derived artifacts + str round-trip parity.

The round-trip tests are the load-bearing ones — they're why migrating a bare
`tuple`/`dict` vocabulary to a `LabeledChoice` subclass is a no-op for every
storage and wire consumer.
"""

import json

import pydantic

from src.domain.models.labeled_choice import LabeledChoice


class Modality(LabeledChoice):
    emdr = "emdr", "EMDR"
    cbt = "cbt", "CBT"


class Service(LabeledChoice):
    psychotherapy = "psychotherapy", "Psychotherapy", "brain"
    medication_management = "medication_management", "Medication management", "pill"
    case_management = "case_management", "Case management"


class Status(LabeledChoice):
    verified = "verified"
    failed = "failed"


def test_values_in_declaration_order():
    assert Modality.values() == ("emdr", "cbt")


def test_value_only_member_labels_fall_back_to_value():
    assert Status.values() == ("verified", "failed")
    assert Status.labels() == {"verified": "verified", "failed": "failed"}
    assert Status.verified.label == "verified"
    assert Status.icons() == {"verified": None, "failed": None}


def test_labels_map_value_to_label():
    assert Modality.labels() == {"emdr": "EMDR", "cbt": "CBT"}


def test_choices_are_ordered_value_label_pairs():
    assert Modality.choices() == (("emdr", "EMDR"), ("cbt", "CBT"))


def test_icons_present_where_declared_none_otherwise():
    assert Service.icons() == {
        "psychotherapy": "brain",
        "medication_management": "pill",
        "case_management": None,
    }


def test_member_is_the_bare_string():
    assert Modality.cbt == "cbt"
    assert str(Modality.cbt) == "cbt"
    assert Modality("cbt") is Modality.cbt


def test_label_attribute_on_member():
    assert Modality.cbt.label == "CBT"
    assert Service.psychotherapy.icon == "brain"
    assert Service.case_management.icon is None


def test_json_serializes_as_plain_value():
    assert (
        json.dumps([Modality.cbt, Service.psychotherapy]) == '["cbt", "psychotherapy"]'
    )


def test_dict_lookup_by_member_hits_string_key():
    labels = Modality.labels()
    assert labels[Modality.cbt] == "CBT"


def test_pydantic_literal_round_trip_emits_plain_strings():
    from typing import Literal

    class M(pydantic.BaseModel):
        picks: list[Literal[Modality.values()]]  # type: ignore[valid-type]

    parsed = M.model_validate({"picks": ["cbt", "emdr"]})
    assert parsed.model_dump(mode="json") == {"picks": ["cbt", "emdr"]}
    assert all(isinstance(p, str) for p in parsed.picks)
